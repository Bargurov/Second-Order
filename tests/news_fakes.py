"""SYNTHETIC news and publication fixtures: feeds refreshed through a simulated network into a temporary inbox, and
press-release pages shaped like the Federal Reserve Board's layout (a div#article with its printed date, title and
release time, a body column, an obfuscated contact line and a last-update line). No page or text here is a real
publication; nothing reaches a network.
"""
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import httpx

from second_order import event_inbox
from test_event_inbox import EIA, FED, WTO, Network, eia_item, eia_rss, rss, rss_item, wto_item, wto_rss

PAGE_TYPE = {"content-type": "text/html; charset=utf-8", "last-modified": "Wed, 16 Sep 2026 18:00:17 GMT"}
PARAGRAPHS = ("The Simulated Committee decided to keep its synthetic policy setting unchanged at 3 percent.",
              "Synthetic indicators suggest that activity expanded at a moderate pace in the third quarter.",
              "Voting for the synthetic action were Member A, Member B and Member C.")


def fed_link(n: int) -> str:
    """The link rss_item(n) gives an entry: a press-release page on the Board's host."""
    return f"https://www.federalreserve.gov/newsevents/pressreleases/monetary2026091{n}a.htm"


def fed_page(date_line: str = "September 16, 2026", title: str = "Simulated Committee issues synthetic statement",
             release_line: str | None = "For release at 2:00 p.m. EDT", paragraphs: tuple[str, ...] = PARAGRAPHS,
             contact: bool = True, linked: str | None = "Implementation Note issued September 16, 2026",
             last_update: str | None = "September 16, 2026", body_extra: str = "", head: str = "",
             articles: int = 1, release_closed: bool = False, attachment: str | None = None) -> bytes:
    """A synthetic page in the Board's press-release layout. As on the Board's own pages, the release-time paragraph is
    left unclosed before the share list unless `release_closed`; `attachment` adds a linked file in the body's
    attachments panel."""
    body = "".join(f"<p>{escape(text)}</p>" for text in paragraphs) + body_extra
    if contact:
        body += ('<p>For media inquiries, please email <a href="/cdn-cgi/l/email-protection#0000">'
                 '<span class="__cf_email__" data-cfemail="0000">[email&#160;protected]</span></a> or call '
                 '202-555-0100.</p>')
    if linked:
        body += f'<p><a href="/newsevents/pressreleases/monetary20260916a1.htm">{escape(linked)}</a></p>'
    if attachment:
        body += ('<div class="panel panel-attachments col-xs-12 col-sm-8 col-md-8"><div class="panel-body">'
                 '<ul class="list-unstyled"><li class="list__icon"><a href="/newsevents/pressreleases/files/'
                 f'monetary20260916a1.pdf">{escape(attachment)}</a></li></ul></div></div>')
    release = (f'<p class="releaseTime">{escape(release_line)}' + ("</p>" if release_closed else "")
               if release_line else "")
    article = (f'<div class="row"><div id="article"><div class="heading col-xs-12 col-sm-8 col-md-8">'
               f'<p class="article__time">{escape(date_line)}</p><h3 class="title">{escape(title)}</h3>{release}'
               '<ul class="list-unstyled"><li class="share btn-group"><a class="shareLink">Share</a>'
               '<ul class="dropdown-menu"><li><a href="https://example.invalid/share">x</a></li></ul></li></ul></div>'
               '<div class="col-xs-12 col-sm-4 col-md-4 hidden-sm"></div>'
               f'<div class="col-xs-12 col-sm-8 col-md-8">{body}</div>'
               '<div class="col-xs-12 col-sm-4 col-md-4"></div></div></div>')
    update = (f'<div class="row"><div id="lastUpdate" class="lastUpdate">Last Update: {escape(last_update)}</div></div>'
              if last_update else "")
    html = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Synthetic</title>'
            f'<script>var x = "<p>not text</p>";</script><style>p {{ color: red }}</style>{head}</head><body>'
            '<nav><p>Navigation that is not the release</p></nav>' + article * articles + update +
            '<footer><p>Footer text</p></footer></body></html>')
    return html.encode("utf-8")


class Pages:
    """A simulated publisher: answers per page address, and every request received."""

    def __init__(self, answers: dict | None = None):
        self.answers = dict(answers or {})
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.get(str(request.url))
        if answer is None:
            raise AssertionError(f"Unexpected request to {request.url}")
        if isinstance(answer, Exception):
            raise answer
        status, body, headers = answer if len(answer) == 3 else (*answer, PAGE_TYPE)
        return httpx.Response(status, content=body, headers=headers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def clock(start: datetime = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)):
    moments = iter(start + timedelta(seconds=n) for n in range(100_000))
    return lambda: next(moments)


def standard_feeds(fed_items: list[str] | None = None, eia_items: list[str] | None = None,
                   wto_items: list[str] | None = None) -> dict:
    """Answers for one refresh without a contact (so the two BLS sources are not requested)."""
    return {FED: [(200, rss(fed_items if fed_items is not None else [
                rss_item(1, title="Simulated Committee issues synthetic statement",
                         description="The Simulated Committee kept the federal funds rate unchanged."),
                rss_item(2, title="Synthetic minutes of the Committee", pub="Wed, 29 Jul 2026 18:00:00 GMT")]))],
            EIA: [(200, eia_rss(eia_items if eia_items is not None else [
                eia_item(1, title="Synthetic natural gas storage rises", pub="Wed, 07 Oct 2026 09:00:00 EDT"),
                eia_item(2, title="Synthetic electricity use by vehicles")]))],
            WTO: [(200, wto_rss(wto_items if wto_items is not None else [
                wto_item(1, title="Synthetic members discuss energy subsidies and tariffs"),
                wto_item(2, title="Synthetic trade forecast update")]))]}


def refreshed(inbox: Path, answers: dict | None = None, at: datetime | None = None) -> Network:
    """One explicit refresh of the synthetic feeds into `inbox`; returns the network with its requests."""
    network = Network(answers if answers is not None else standard_feeds())
    event_inbox.refresh(inbox, network.fetcher(contact=None), clock(at) if at else clock())
    return network
