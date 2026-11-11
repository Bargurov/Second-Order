"""Publisher feeds: the connected publishers' feeds (news_registry), refreshed only by the operator's explicit action.

The Event Inbox's machinery does the work unchanged (event_inbox.refresh_source): each feed is requested once, with no
redirect, retry or proxy, a timeout and a size cap, only at its registered address, and its entries are checked and
reduced to plain metadata; each source's record keeps its last successful result; the local archive keeps entries after
they leave the feed; every request leaves a write-once retrieval record. The cache is data/news-feeds/, apart from the
Event Inbox's data/event-inbox/, so the operator's official inbox, its views and its processing are unchanged.

A publisher whose terms allow headlines only (``excerpts`` off) never has its excerpts kept, and no complete response
of a third-party publisher is kept (``keep_raw`` off). Reading (``feed_view``) only reads the cache: no network, no
writes. Which publishers are requested is fixed at startup (the registry's connected publishers; tests and the demo
launcher pass SYNTHETIC ones), never chosen by a request.
"""
from datetime import datetime
import os
from pathlib import Path
from typing import Callable

from . import event_inbox, inbox_acquisitions, inbox_archive
from .news_registry import Publisher

FEEDS_VERSION = "news-feeds-0.1"
ROOT = Path(__file__).resolve().parent.parent
FEEDS_DIR = ROOT / "data" / "news-feeds"  # Runtime cache; data/ is ignored by git.


def refreshable(publishers: dict[str, Publisher]) -> list[Publisher]:
    """The publisher feeds a refresh requests: the registry's connected ones (and SYNTHETIC ones a test installed)."""
    return [publisher for publisher in publishers.values() if publisher.feed is not None and
            (publisher.status == "connected" or publisher.synthetic)]


def fetcher_for(publishers: list[Publisher], transport=None, contact: str | None = None) -> event_inbox.FeedFetcher:
    """A fetcher that may request exactly these publishers' feeds and nothing else. On the real network (no
    ``transport``) the operator's contact, when SECOND_ORDER_FEED_CONTACT sets one, goes in its User-Agent, as the SEC's
    and the ONS's fair-access rules ask; a feed that requires one is not requested without it."""
    if transport is None and contact is None:
        contact = os.environ.get(event_inbox.CONTACT_ENV, "").strip() or None
    return event_inbox.FeedFetcher(contact, transport, frozenset(publisher.feed.feed_url for publisher in publishers))


def refresh(folder: Path, fetcher: event_inbox.FeedFetcher, publishers: list[Publisher],
            clock: Callable[[], datetime] = event_inbox.now) -> dict:
    """The explicit refresh: each publisher's feed once, in registry order, with no retry; then the view."""
    outcomes = [event_inbox.refresh_source(publisher.feed, fetcher, folder, clock) for publisher in publishers]
    return {**feed_view(folder, publishers), "refreshed": outcomes}


def _official(link: str, source: event_inbox.Source) -> bool:
    try:
        event_inbox.official_link(link, source)
        return True
    except event_inbox.FeedRejected:
        return False


def feed_view(folder: Path, publishers: list[Publisher]) -> dict:
    """Each publisher feed's state and latest request, its current entries and the archive's retained ones. Reads
    only; an unreadable record or archive is reported, never repaired."""
    sources, items, retained = [], [], []
    for publisher in publishers:
        source = publisher.feed
        state, record, problem = event_inbox.read_record(folder, source.key, source)
        success = record["last_success"] if record else None
        attempt = record["last_attempt"] if record else None
        shown = ("never_refreshed" if state == "missing" else "unreadable" if state == "unreadable"
                 else attempt["outcome"])
        archive_state, archive, archive_problem = inbox_archive.read_archive(
            folder, source.key, source.feed_url, lambda link, source=source: _official(link, source),
            creator=source.credit_creator)
        current = (success or {}).get("items", [])
        kept = inbox_archive.retained_items(archive, {item["id"] for item in current})
        sources.append({"key": source.key, "label": source.label, "publisher": source.publisher,
                        "kind": source.kind, "attribution": source.attribution, "feed_url": source.feed_url,
                        "catalogue_url": source.catalogue_url, "terms_url": source.terms_url, "state": shown,
                        "problem": problem, "last_attempt": attempt,
                        "last_success": None if success is None else {
                            "retrieved_at": success["retrieved_at"], "listed": success["listed"],
                            "item_count": len(success["items"]), "skipped_count": success["skipped_count"]},
                        "archive": {"state": archive_state, "problem": archive_problem, "retained": len(kept)},
                        "acquisitions": inbox_acquisitions.latest(folder, source.key, source.feed_url)})
        for item in current:
            items.append({**{key: value for key, value in item.items() if key != "identity"}, "source": source.key,
                          "retrieved_at": success["retrieved_at"], "last_seen_at": success["retrieved_at"],
                          "stale": shown != "ok", "content_sha256": inbox_archive.content_sha256(item)})
        for item in kept:
            retained.append({**item, "source": source.key, "retrieved_at": item["last_seen_at"], "stale": False,
                             "content_sha256": inbox_archive.content_sha256(item)})
    return {"feeds_version": FEEDS_VERSION, "sources": sources, "items": items, "retained": retained}
