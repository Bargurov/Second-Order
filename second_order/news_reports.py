"""Reports: every feed entry the local caches hold, official and publisher, as the news reads them (news-report-0.1).

The pool joins the Event Inbox cache (the five official feeds) and the publisher-feed cache (news_feeds), current
entries and retained ones, and gives each the registry's word on it (news_registry): its publisher's role (an official
release, a news report or a company's statement), what may be shown (the headline and link, and the feed's excerpt only
where the publisher allows it), and whether it may be material for a shared brief or a deeper analysis. A report's time
is the instant its feed states (``at_basis`` ``published``); when the feed states a calendar date but no usable time (a
date-only feed's placeholder, or a time whose zone contradicts its date), the end of that date in UTC, or when this
server first saw it if that was earlier (``dated``), so a dated release first retrieved days later is not taken for a
new one; otherwise when this server first saw it (``first_seen``). Every view says which.
Reading the pool reads the caches only: no publisher is contacted and nothing is written.
"""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from email.utils import parsedate_tz
from pathlib import Path

from . import event_inbox, news_feeds, user_news
from .news_registry import PUBLISHERS, ROLE_LABEL, Publisher

REPORT_VERSION = "news-report-0.1"


def topics(publisher: Publisher, title: str, excerpt: str | None) -> list[dict]:
    """The interests a report concerns: its publisher's own topic (when it has one), and every interest whose terms it
    names."""
    found = user_news.topics(publisher.key, title, excerpt)
    own = publisher.interest
    if own is not None and not any(row["interest"] == own and row["basis"] == "source" for row in found):
        terms = next((row["terms"] for row in found if row["interest"] == publisher.interest), [])
        found = [row for row in found if row["interest"] != publisher.interest]
        found.append({"interest": publisher.interest, "basis": "source", "terms": terms})
    order = [interest.slug for interest in user_news.INTERESTS]
    return sorted(found, key=lambda row: order.index(row["interest"]))


def stated_day(published: dict) -> str | None:
    """The calendar date a feed states for an entry whose time is not a usable instant, or None."""
    if published["state"] == "date_only":
        return published["date"]
    if published["state"] != "unstated" or not published["as_stated"]:
        return None
    parsed = parsedate_tz(published["as_stated"])
    try:
        return date(parsed[0], parsed[1], parsed[2]).isoformat() if parsed else None
    except ValueError:
        return None


def report_time(published: dict, first_seen: str) -> tuple[str, str]:
    """(the report's time, its basis): the stated instant; else the stated date's end in UTC or the first sighting,
    whichever is earlier; else the first sighting."""
    if published["state"] == "stated":
        return published["utc"], "published"
    day = stated_day(published)
    seen = datetime.fromisoformat(first_seen)
    if day is not None:
        start = datetime.combine(date.fromisoformat(day), time(0), timezone.utc)
        if seen >= start:  # A date later than the first sighting is not believed; the sighting is used.
            end = start + timedelta(days=1, seconds=-1)
            return (first_seen if seen <= end else end.isoformat()), "dated"
    return first_seen, "first_seen"


def attribution(publisher: Publisher, item: dict) -> str:
    """The credit a report carries: its publisher's, preceded by the entry's creator where the publisher's licence asks
    for the creator to be credited (event_inbox.Source.credit_creator)."""
    creator = item.get("creator")
    return f"By {creator} for {publisher.attribution}" if creator else publisher.attribution


def _report(item: dict, listing: str, publisher: Publisher, source: event_inbox.Source) -> dict:
    shown_excerpt = item["excerpt"] if publisher.display == "headline_excerpt" and item["excerpt"] and \
        not item["excerpt_repeats_title"] else None
    published = user_news.published(item["feed_timestamp"], source)
    first_seen = item["first_seen_at"]
    last_seen = item["retrieved_at"] if listing == "current" else item["last_seen_at"]
    at, basis = report_time(published, first_seen)
    return {"report_version": REPORT_VERSION, "entry_id": item["id"], "version_sha256": item["content_sha256"],
            "source": publisher.key, "publisher": publisher.name, "role": publisher.role,
            "role_label": ROLE_LABEL[publisher.role], "kind": source.kind, "attribution": attribution(publisher, item),
            "title": item["title"], "title_shortened": item["title_truncated"], "excerpt": shown_excerpt,
            "excerpt_shortened": bool(shown_excerpt) and item["excerpt_truncated"], "link": item["link"],
            "published": published, "first_seen_at": first_seen, "last_seen_at": last_seen, "listing": listing,
            "stale": bool(item.get("stale")),
            "at": at, "at_basis": basis,
            "topics": topics(publisher, item["title"], shown_excerpt), "display": publisher.display,
            "material": publisher.material, "synthetic": publisher.synthetic}


def _index_report(row: dict) -> dict:
    """An article the GDELT index listed and the operator attached to a story (news_index): its publisher is its
    domain, its title as indexed, its link; no excerpt, no text, never material."""
    from . import news_index
    seen = news_index._seen(row.get("seendate")) or row["attached_at"]
    return {"report_version": REPORT_VERSION, "entry_id": row["entry_id"],
            "version_sha256": hashlib.sha256(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest(),
            "source": news_index.SOURCE_KEY, "publisher": (row.get("domain") or "unknown").lower(), "role": "news",
            "role_label": ROLE_LABEL["news"], "kind": "News article listed by the GDELT index",
            "attribution": news_index.ATTRIBUTION, "title": row.get("title") or row["url"], "title_shortened": False,
            "excerpt": None, "excerpt_shortened": False, "link": row["url"],
            "published": {"as_stated": None, "element": None, "state": "unstated", "utc": None, "date": None,
                          "note": (f"Kept from a GDELT index lookup attached "
                                   f"{row['attached_at'][:16].replace('T', ' ')} UTC: the index saw it at {seen} and "
                                   "states no publication time. It is not checked again unless an editor looks the "
                                   "story up again.")},
            "first_seen_at": row["attached_at"], "last_seen_at": row["attached_at"], "listing": "current",
            "stale": False, "at": seen, "at_basis": "first_seen", "topics": [], "display": "headline",
            "material": "none", "synthetic": False, "indexed": True}


def pool(inbox: Path, feeds: Path, publishers: dict[str, Publisher] | None = None, index: Path | None = None) -> dict:
    """{reports: {entry_id: report}, sources: [what each source holds and how fresh it is]}. Reads only. ``index``
    adds the articles the operator attached from the GDELT index (news_index)."""
    publishers = publishers or PUBLISHERS
    official = event_inbox.inbox_view(inbox)
    third = [publisher for publisher in publishers.values() if publisher.feed is not None]
    others = news_feeds.feed_view(feeds, third)
    reports: dict[str, dict] = {}
    for view, sources in ((official, event_inbox.SOURCES), (others, {p.key: p.feed for p in third})):
        for listing, rows in (("current", view["items"]), ("retained", view["retained"])):
            for item in rows:
                if item["source"] in publishers and item["id"] not in reports:
                    reports[item["id"]] = _report(item, listing, publishers[item["source"]], sources[item["source"]])
    rows = []
    for source in official["sources"] + others["sources"]:
        publisher = publishers.get(source["key"])
        if publisher is None:
            continue
        success = source["last_success"]
        attempt = source["last_attempt"]
        rows.append({"source": source["key"], "publisher": publisher.name, "label": source["label"],
                     "role": publisher.role, "role_label": ROLE_LABEL[publisher.role], "state": source["state"],
                     "last_success_at": success["retrieved_at"] if success else None,
                     "last_attempt_at": (attempt["finished_at"] or attempt["started_at"]) if attempt else None,
                     "stale": success is not None and source["state"] != "ok",
                     "reports": sum(1 for report in reports.values() if report["source"] == source["key"]),
                     "display": publisher.display, "material": publisher.material,
                     "attribution": publisher.attribution, "terms_url": publisher.terms_url,
                     "status": publisher.status, "synthetic": publisher.synthetic})
    if index is not None and "gdelt-index" in publishers:
        from . import news_index
        held = news_index.entries(index)
        for row in held:
            reports.setdefault(row["entry_id"], _index_report(row))
        latest = news_index.last_lookup(index)
        publisher = publishers["gdelt-index"]
        rows.append({"source": publisher.key, "publisher": publisher.name, "label": "GDELT Project: news index lookups",
                     "role": publisher.role, "role_label": ROLE_LABEL[publisher.role],
                     "state": "never_refreshed" if latest is None else "ok" if latest["outcome"] == "ok" else "failed",
                     "last_success_at": latest["requested_at"] if latest and latest["outcome"] == "ok" else None,
                     "last_attempt_at": latest["requested_at"] if latest else None, "stale": False,
                     "reports": len(held), "display": publisher.display, "material": publisher.material,
                     "attribution": publisher.attribution, "terms_url": publisher.terms_url, "status": publisher.status,
                     "synthetic": publisher.synthetic})
    return {"reports": reports, "sources": rows}


def publisher_names(publishers: dict[str, Publisher] | None = None) -> set[str]:
    """Publisher names, case-folded, as a headline's trailing credit may give them."""
    return {publisher.name.casefold() for publisher in (publishers or PUBLISHERS).values()}
