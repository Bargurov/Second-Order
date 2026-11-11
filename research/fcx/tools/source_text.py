"""Page texts of the four retained FCX documents, the same way every time.

All four are SEC EDGAR HTML: the 10-K's inline XBRL (approval copper-sec-01), and the SEC copies of the 10-Q and of the
two releases filed as 8-K exhibits 99.1 (approval fcx-sec-docs-02, SEC_COPIES). Each is split at its page breaks, with
the hidden XBRL header removed, table cells separated by spaces and character references decoded. Tags are matched in
either case (the Bagdad exhibit writes them in capitals); a last part after the final page break that carries no text
is not a page. ``normal`` collapses whitespace, so a quote is checked against the page text whatever the line breaks.
Reads local files only.

IR_PDF_COPIES names the earlier investor-relations PDFs of the three later documents, kept privately; the package no
longer reads them. ``ir_pdf_pages`` reads them with pypdf, one text per PDF page, for comparison only
(tools/sec_match.py).

Run ``python -I source_text.py <source id> <out folder>`` to write one normalized text file per page.
"""
import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FCX = REPO / "data/company-sources/fcx"
SEC_COPIES = {
    "10q-2026q3": FCX / "sec-10q-2026q3/fcx-20260930.htm",
    "release-2026q3": FCX / "sec-8k-2026-10-27/a3q2026exhibit991.htm",
    "news-2026-11-04": FCX / "sec-8k-2026-11-04/fcx_261104.htm",
}
SOURCES = {"10k-2025": FCX / "sec-10k-2025/fcx-20251231.htm", **SEC_COPIES}
IR_PDF_COPIES = {  # for comparison only
    "10q-2026q3": FCX / "ir-10q-2026q3/FCX-Q326-10-Q.pdf",
    "release-2026q3": FCX / "ir-release-2026q3/FCX_261027_3Q_2026_Earnings_Release.pdf",
    "news-2026-11-04": FCX / "ir-news-2026-11-04/FCX_261104.pdf",
}


def normal(text: str) -> str:
    """One line, single spaces, typographic quotes and dashes kept as printed."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader
    return [normal(page.extract_text() or "") for page in PdfReader(str(path)).pages]


def html_pages(path: Path) -> list[str]:
    text = path.read_bytes().decode("utf-8")
    text = re.sub(r"<ix:header>.*?</ix:header>", " ", text, flags=re.S)
    parts = re.split(r"<hr[^>]*page-break-after:\s*always[^>]*/?>|"
                     r"<div[^>]*page-break-(?:after|before):\s*always[^>]*>", text, flags=re.I)
    pages = []
    for part in parts:
        part = re.sub(r"<(?:br|/p|/div|/tr|/li|/h\d|/t[dh])[^>]*>", " ", part, flags=re.I)
        pages.append(normal(html.unescape(re.sub(r"<[^>]+>", "", part))))
    if len(pages) > 1 and not pages[-1]:
        pages.pop()
    return pages


def pages(source: str) -> list[str]:
    return html_pages(SOURCES[source])


def sec_pages(source: str) -> list[str]:
    """The SEC EDGAR copy of the 10-Q or of one of the two releases."""
    return html_pages(SEC_COPIES[source])


def ir_pdf_pages(source: str) -> list[str]:
    """The earlier investor-relations PDF of the same document: for comparison only."""
    return pdf_pages(IR_PDF_COPIES[source])


if __name__ == "__main__":
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for number, text in enumerate(pages(sys.argv[1]), 1):
        (out / f"{number:03d}.txt").write_bytes(text.encode("utf-8"))
    print(sys.argv[1], number, "pages")
