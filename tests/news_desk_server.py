"""Serve the news-first journey on the real application for the stories browser check and the local demo.

Not a test module. It is started with a new, empty folder (``--root``) and writes everything inside it; nothing under
data/ is written. It makes the SYNTHETIC accounts, credit terms and usage limits of tests/account_fakes.py (passwords
are SYNTHETIC test strings), refreshes the SYNTHETIC publishers of tests/news_desk_fakes.py through a simulated network
(their reports are dated relative to the time the launcher starts, so Hot now has current SYNTHETIC developments, and
every title, publisher and page says "Synthetic"), and curates them through the real actions (news_desk_fakes.curate):
a published brief, a merged story, a topic of three developments. A second refresh then answers one SYNTHETIC feed
with HTTP 503, so the page shows an honest stale state.

``--records FOLDER`` (the demo) also serves COPIES of real retained caches: FOLDER/event-inbox/ (the official feeds as
the Event Inbox last retrieved them), FOLDER/news-feeds/ (the connected publishers as their last explicit refresh
left them), FOLDER/news-texts/ (retained official texts) and FOLDER/news-index/ (index lookups and the articles
attached to stories). The folder is only read; those reports keep their real times, so old ones are shown as older news, and they
are grouped like any other. Without it, the official and connected caches are empty. ``--newsroom FILE`` also starts
from a COPY of a real newsroom store (made with SQLite's online backup, so the original may be in use), so the
operator's real stories, topics and published briefs are served beside the SYNTHETIC ones; the original is only read.

Every fetcher is simulated: the Event Inbox's and the News desk's feed fetchers answer only the SYNTHETIC feeds and
refuse every real address, so a refresh pressed in the demo never reaches a publisher; the paid analysis sender
(``--simulated-provider``) is the in-process fake of tests/review_browser_server.py, and the paid brief sender
(``--simulated-drafting``) the fake of news_desk_fakes.BriefModel. Every request any fake receives is recorded under
the served folder (simulated-feeds/requests.jsonl, simulated-provider/, simulated-drafting/requests.jsonl). Nothing can
reach a network, and no real key is read.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from news_desk_fakes import (GAZETTE, MAKER, MINE, UNRELATED, BriefModel, Feeds, curate, desk_in,  # noqa: E402
                             homes_item, insufficient_economics, later_items, publish_banks, publish_homes,
                             publish_wire, survey_items, trade_feeds, wire_item)
from review_browser_server import simulated_sender, synthetic_accounts, synthetic_usage_policy  # noqa: E402
from second_order import event_inbox, news_feeds, newsroom_store  # noqa: E402
from second_order.api import create_app  # noqa: E402

DRAFTING_KEY = "sk-ant-dummy-simulated-drafting-key-0000"  # A dummy credential; no real key is ever read.


class Recorded(Feeds):
    """The SYNTHETIC feeds, every request appended to a file (and refused when it is not a SYNTHETIC feed)."""

    def __init__(self, answers: dict, log: Path):
        super().__init__(answers)
        self.log = log
        log.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.log.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"method": request.method, "url": str(request.url)}) + "\n")
        return super().__call__(request)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="an empty folder for every file this serves")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--static-root", type=Path, default=ROOT / "frontend",
                        help="isolated frontend build folder containing dist/ and dist-client/ (defaults to frontend/)")
    parser.add_argument("--records", type=Path, default=None,
                        help="a folder holding event-inbox/ and news-feeds/ to serve copies of (only read)")
    parser.add_argument("--newsroom", type=Path, default=None,
                        help="a newsroom.db to serve a copy of (only read), with --records for its reports")
    parser.add_argument("--simulated-provider", action="store_true", help="paid analyses against the in-process fake")
    parser.add_argument("--simulated-drafting", action="store_true", help="paid brief drafts against the fake")
    parser.add_argument("--fidelity-case", action="store_true", help=(
        "also publish the SYNTHETIC annual-rate, bank lending survey and opened-investigation briefs "
        "(news_desk_fakes.homes_brief, banks_brief, wire_brief) the fidelity browser check reads"))
    parser.add_argument("--later-feeds", action="store_true", help=(
        "the SYNTHETIC feeds answer later entries to an update run's refresh (the setup is dated an hour earlier, "
        "past the update cooldown)"))
    args = parser.parse_args()
    if not args.root.is_dir() or any(args.root.iterdir()):
        parser.error("--root must be an existing, empty folder")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if args.later_feeds:
        now -= timedelta(hours=1)  # The setup an hour ago, so an update's refresh is past its cooldown.
    if args.records is not None:
        for part in ("event-inbox", "news-feeds", "news-texts", "news-index"):
            if (args.records / part).is_dir():
                shutil.copytree(args.records / part, args.root / part)
    if args.newsroom is not None:
        if not args.newsroom.is_file():
            parser.error("--newsroom must name an existing newsroom.db")
        (args.root / "newsroom").mkdir()
        original = sqlite3.connect(f"file:{args.newsroom.resolve().as_posix()}?mode=ro", uri=True)
        copy = sqlite3.connect(args.root / "newsroom" / "newsroom.db")
        try:
            original.backup(copy)
        finally:
            original.close()
            copy.close()
        newsroom_store.open_at(args.root / "newsroom").upgrade()  # The copy only: a newsroom-1 copy gains two tables.
    accounts = args.root / "accounts" / "accounts.db"
    synthetic_accounts(accounts)
    synthetic_usage_policy(accounts)
    answers = trade_feeds(now, courier_extra=[homes_item(now), *survey_items(now), wire_item(now)]
                          if args.fidelity_case else None)
    network = Recorded(answers, args.root / "simulated-feeds" / "requests.jsonl")
    drafting = BriefModel(DRAFTING_KEY) if args.simulated_drafting else None
    if drafting is not None and args.later_feeds:  # Valid answers for any SYNTHETIC story the update reaches.
        drafting.economics = insufficient_economics
        drafting.verdicts = {MINE: "outside_scope", UNRELATED: "outside_scope"}
    desk = desk_in(args.root, network=network, drafting=drafting.sender() if drafting else None)
    synthetic = [publisher for publisher in desk.publishers.values() if publisher.synthetic]
    news_feeds.refresh(desk.feeds, desk.fetcher, synthetic, lambda: now)
    curate(desk, now, method="synthetic")
    if args.fidelity_case:
        publish_homes(desk, now)
        publish_banks(desk, now)
        publish_wire(desk, now)  # Who says what about an opened procedure (story-brief-0.4).
    network.answers[GAZETTE.feed_url] = (503, b"")  # A later refresh fails for one feed: its reports become stale.
    news_feeds.refresh(desk.feeds, desk.fetcher, [desk.publishers["synthetic-gazette"]], lambda: now)
    if args.later_feeds:  # What an update finds: new, late, undated, repeated and revised entries; one feed's 503.
        network.answers.update(trade_feeds(now, **later_items(lambda hours: now + timedelta(minutes=10 * hours))))
        network.answers[MAKER.feed_url] = (503, b"")
    # From here on the server's own refreshes reach only the SYNTHETIC feeds; every real address is refused.
    refuse = event_inbox.FeedFetcher(None, httpx.MockTransport(network))
    desk = replace(desk, fetcher=news_feeds.fetcher_for(
        [publisher for publisher in desk.publishers.values() if publisher.feed],
        httpx.MockTransport(network)))
    if drafting is not None:
        log = args.root / "simulated-drafting" / "requests.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        handler = drafting.handler

        def recorded(request: httpx.Request) -> httpx.Response:
            with log.open("a", encoding="utf-8") as file:
                file.write(json.dumps({"url": str(request.url)}) + "\n")
            return handler(request)
        drafting.handler = recorded
    paid = simulated_sender(args.root / "simulated-provider") if args.simulated_provider else None
    app = create_app(args.root / "prepared", args.static_root / "dist", args.root / "prepared-drafts",
                     args.root / "reviews", args.root / "intake", args.root / "tracker-attempts", paid=paid,
                     inbox=args.root / "event-inbox", feeds=refuse, links=args.root / "event-links",
                     store=args.root / "store" / "research.db", accounts=accounts,
                     client_static=args.static_root / "dist-client", desk=desk)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
