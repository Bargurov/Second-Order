"""SYNTHETIC retained BIS snapshots for tests and the browser test server: invented press-release records in the shape of
BIS's News & Updates listing data, a page that embeds them, and acquisition records that describe the written bytes
exactly. Nothing here is BIS's text, except one record that reuses a real release address and date (UAE) so that
Related research's same-event rule can be exercised against the committed case library."""
import hashlib
import json
from pathlib import Path

APPROVAL = "bis-semis-sources-01"
PAGE_URL = "https://www.bis.gov/news-updates"
RETRIEVED = "2026-10-12T14:47:42.973565+00:00"
UAE_PATH = "/press-release/department-commerce-eases-export-controls-uae"


def stamp(time: str | None) -> dict | None:
    """A listing timestamp as BIS's data states one (UTC), or None."""
    if time is None:
        return None
    from datetime import datetime
    return {"timestamp": int(datetime.fromisoformat(time).timestamp()), "timezone": "UTC", "offset": "+00:00",
            "time": time}


def teaser(number: int, title: str, path: str, published: str | None = "2026-03-02T15:00:00+00:00",
           body: str | None = "<p>Synthetic release text.</p><p>###</p>", topics=("Regulations",), countries=(),
           external: str | None = None, summary: str | None = None, status: bool = True,
           typename: str = "NodePressRelease", created: str = "2026-03-02T14:00:00+00:00") -> dict:
    return {"__typename": typename, "id": str(9000 + number), "uuid": f"00000000-0000-4000-8000-{number:012d}",
            "created": stamp(created), "changed": stamp("2026-09-04T21:00:00+00:00"),
            "metatag": [{"tag": "meta", "attributes": {"name": "title", "content": title}}],
            "body": None if body is None else {"processed": body, "format": "full_html", "summary": summary or ""},
            "externalLink": None if external is None else {"__typename": "Link", "title": "Synthetic other agency",
                                                           "url": external, "internal": False},
            "newsUpdatesTopic": [{"id": "7", "name": topic} for topic in topics] or None,
            "path": path, "publishedOn": stamp(published), "countryTag": [{"id": "1", "name": c} for c in countries]
            or None, "status": status, "sticky": False, "title": title}


def records() -> list:
    """The standard SYNTHETIC listing: usable records of each kind, and entries that cannot be used."""
    copy = teaser(9, "Synthetic Duplicate Copy", "/press-release/synthetic-duplicate-copy",
                  published="2026-01-05T16:00:00+00:00", body="<p>Same text.</p>")
    return [
        teaser(1, "Synthetic Commerce Tightens Controls on Advanced Computing Chips",
               "/press-release/synthetic-tightens-controls-advanced-computing-chips",
               published="2026-09-30T16:00:00+00:00",
               body="<p>WASHINGTON, D.C. &mdash; Synthetic: BIS adds export controls on advanced computing chips and "
                    "semiconductor manufacturing equipment.</p><p>Synthetic second paragraph.</p><p>###</p>",
               countries=("China",)),
        teaser(2, "Synthetic Settlement over Ion Implanters", "/press-release/synthetic-settlement-ion-implanters",
               published="2026-08-14T16:00:00+00:00", topics=("Enforcement",),
               body="<p>Synthetic: a company agreed to pay a penalty for shipping semiconductor manufacturing "
                    "equipment to a party on the Entity List.</p><p>###</p>"),
        teaser(3, "Synthetic Firearms Exporter Sentenced", "/press-release/synthetic-firearms-exporter-sentenced",
               published="2026-07-01T16:00:00+00:00", topics=("Enforcement",), body=None,
               external="https://www.justice.gov/usao/pr/synthetic-firearms-exporter-sentenced"),
        teaser(4, "Synthetic Record without a Listing Date", "/press-release/synthetic-record-without-listing-date",
               published=None, created="2026-02-01T00:00:00+00:00"),
        teaser(5, "Synthetic Repeated Title", "/press-release/synthetic-repeated-title",
               published="2026-05-01T16:00:00+00:00", body="<p>Synthetic first document.</p>"),
        teaser(6, "Synthetic Repeated Title", "/press-release/synthetic-repeated-title-0",
               published="2026-06-01T16:00:00+00:00", body="<p>Synthetic second, different document.</p>"),
        teaser(7, "Synthetic Markup Test", "/press-release/synthetic-markup-test",
               published="2026-04-01T16:00:00+00:00",
               body="<p onclick=\"alert(1)\">Plain &amp; safe &lt;b&gt; text</p><script>alert('x')</script>"
                    "<style>p{color:red}</style><iframe src=\"https://example.invalid/\">hidden</iframe>"
                    "<p><a href=\"javascript:alert(2)\">a link's words</a> stay as words</p>",
               summary="<p>Synthetic <strong>summary</strong></p>"),
        teaser(8, "Department of Commerce Eases Export Controls for UAE", UAE_PATH,
               published="2026-07-10T15:15:00+00:00",
               body="<p>Synthetic stand-in text for the UAE release address.</p><p>###</p>"),
        copy,
        dict(copy),  # The same record listed twice: an identical copy.
        teaser(11, "Synthetic Conflicting Copy", "/press-release/synthetic-conflicting-copy",
               published="2026-01-06T16:00:00+00:00", body="<p>One text.</p>"),
        teaser(12, "Synthetic Conflicting Copy", "/press-release/synthetic-conflicting-copy",
               published="2026-01-06T16:00:00+00:00", body="<p>Another text.</p>"),
        teaser(13, "", "/press-release/synthetic-no-title"),
        teaser(14, "Synthetic Outside Address", "/news/synthetic-outside-address"),
        teaser(15, "Synthetic Unpublished", "/press-release/synthetic-unpublished", status=False),
        teaser(16, "Synthetic Plain HTTP Link", "/press-release/synthetic-plain-http-link",
               external="http://justice.gov/synthetic"),
        {**teaser(17, "Synthetic Ambiguous Date", "/press-release/synthetic-ambiguous-date"),
         "publishedOn": {"timestamp": 1, "timezone": "UTC", "offset": "+00:00", "time": "2026-03-03T10:00:00+00:00"}},
    ]


def page(teasers: list, blocks: int = 1, data: str | None = None) -> bytes:
    # Next.js escapes "<" inside its embedded JSON (as the retained page shows), so markup in a body cannot end the
    # script element early.
    payload = data if data is not None else json.dumps(
        {"props": {"pageProps": {"pressReleaseTeasers": teasers, "newsUpdatesTopics": []}}, "page": "/news-updates"}
    ).replace("<", "\\u003c")
    script = f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
    return ("<!DOCTYPE html><html><head><title>News and Updates | Bureau of Industry and Security</title></head>"
            f"<body><main><h1>News &amp; Updates</h1></main>{script * blocks}</body></html>").encode("utf-8")


def release_page(title: str, date: str, text_html: str) -> bytes:
    return ("<!DOCTYPE html><html><body><svg><title>Lock</title></svg><nav><a href=\"/\">Home</a></nav>"
            f"<div>FOR IMMEDIATE RELEASE | {date} | Media Contact: <span>[email protected]</span></div>"
            f"<h1>{title}</h1><a href=\"/x.pdf\">Download as PDF</a><div>{text_html}</div>"
            "<footer><p>Footer text.</p></footer></body></html>").encode("utf-8")


def outcome(number: int, url: str, folder: str, data: bytes, **changes) -> dict:
    record = {"approval_id": APPROVAL, "n": number, "url": url, "outcome": "complete", "http_status": 200,
              "body_state": "fully_read", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "hash_kind": "complete_response", "retained": f"data/sector-sources/bis/{folder}/source.html",
              "retention": "acquired_not_accepted", "body_completed_at": RETRIEVED,
              "named_headers": {"content-type": "text/html; charset=utf-8", "content-encoding": None}}
    return {**record, **changes}


def write_snapshot(root: Path, teasers: list | None = None, releases: dict | None = None,
                   page_bytes: bytes | None = None, **changes) -> Path:
    """A retained-sources folder (its acquisition records, the page and any release pages) under ``root``."""
    data = page_bytes if page_bytes is not None else page(records() if teasers is None else teasers)
    run = root / "acquisitions" / APPROVAL
    run.mkdir(parents=True, exist_ok=True)
    (root / "news-updates").mkdir(parents=True, exist_ok=True)
    (root / "news-updates" / "source.html").write_bytes(data)
    (run / "outcome-1.json").write_text(json.dumps(outcome(1, PAGE_URL, "news-updates", data, **changes)),
                                        encoding="utf-8")
    for number, (path, html) in enumerate((releases or {}).items(), start=2):
        folder = f"release-{number}"
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / "source.html").write_bytes(html)
        (run / f"outcome-{number}.json").write_text(json.dumps(outcome(
            number, f"https://www.bis.gov{path}", folder, html)), encoding="utf-8")
    return root


def standard_releases() -> dict:
    """Retained release pages for record 1 (identical text) and record 2 (different text)."""
    return {"/press-release/synthetic-tightens-controls-advanced-computing-chips": release_page(
                "Synthetic Commerce Tightens Controls on Advanced Computing Chips", "September 30, 2026",
                "<p>WASHINGTON, D.C. &mdash; Synthetic: BIS adds export controls on advanced computing chips and "
                "semiconductor manufacturing equipment.</p><p>Synthetic second paragraph.</p><p>###</p>"),
            "/press-release/synthetic-settlement-ion-implanters": release_page(
                "Synthetic Settlement over Ion Implanters", "August 14, 2026",
                "<p>Synthetic: a longer release text than the listing gives.</p><p>Another paragraph.</p><p>###</p>")}
