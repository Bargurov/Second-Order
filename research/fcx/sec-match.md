# FCX: the records and passages matched against the SEC copies

Three of the four documents were first read from investor-relations PDFs: the third-quarter 2026 Form 10-Q, the
results release of 27 October 2026 and the Bagdad release of 4 November 2026. On 2026-11-10 the owner approved
obtaining their SEC EDGAR copies. The two releases are exhibits 99.1 to Forms 8-K (the results release furnished under Items 2.02 and 7.01, the Bagdad release attached under Item 8.01). The copies were
retained under approvals fcx-sec-locate-02, fcx-sec-index-02 and fcx-sec-docs-02.

Every published record and passage that rests on these three documents was matched against the SEC text:
755 items, 648 records and 107 passages. `tools/sec_match.py` did the matching, and `sec-match.json` lists each
item with its class, its old and new place and a note.

## Result

| Document | SEC copy | Items | exact | typography | relaid | not_found |
| --- | --- | --- | --- | --- | --- | --- |
| `10q-2026q3` | Form 10-Q, accession 0000831259-26-000051 | 426 (364 records, 62 passages) | 423 | 3 | 0 | 0 |
| `release-2026q3` | Form 8-K of 2026-10-27, exhibit 99.1, accession 0000831259-26-000045 | 301 (269 records, 32 passages) | 298 | 3 | 0 | 0 |
| `news-2026-11-04` | Form 8-K of 2026-11-04, exhibit 99.1, accession 0000831259-26-000048 | 28 (15 records, 13 passages) | 28 | 0 | 0 | 0 |
| All | | 755 | 749 | 6 | 0 | 0 |

- **not_found:** none.
- **Changed definitions:** none. Every record keeps its metric, unit, basis, period, row, column, value and printed
  figure, and every passage its topic.
- **Nothing is held back.** With no item not found and no definition changed, the re-pointed package keeps every
  record and passage.

## What was checked

For each item:

- the quote occurs on its page of the SEC copy, after whitespace normalization;
- a record's printed figure sits in its quote as a whole figure, so it is on that page;
- the SEC page prints the item's printed page;
- the SEC page holds the same words and figures, in the same order, as the PDF page the item was first checked on.
  So each table's headings, unit lines ("(In millions...)"), column labels and row labels are where they were, and the
  metric and basis read as before.

Two things were set aside as layout, not wording:

- the 10-Q's running "Table of Contents" link, at the top of each SEC page and the foot of each PDF page;
- the EDGAR envelope and file title before page 1 of each SEC copy.

## Pages

Each SEC copy splits at its page breaks into the same number of pages as its PDF: 71, 40 and 3. Every item keeps its
file page, printed page and location.

- **10-Q:** file page = printed page for pages 2 to 70; page 71 is S-1; the cover has no number.
- **Results release:** pages 1 to 12 are numbered 1 to 12, and the supplemental schedules (13 to 40) I to XXVIII.
- **Bagdad release:** pages 1 to 3, numbered 1 to 3. The PDF's text split four words on page 2 ("facilitie s",
  "crus her", "approx imately", "concent rator"); the SEC text has them whole. No quote used them.

## The six typography items

In each case the PDF text had a space that the SEC text does not. The stored quote is now the SEC wording, verbatim.

| Id | Kind | Document, page | PDF text | SEC text |
| --- | --- | --- | --- | --- |
| `r3-out-cu-price-q4-2026` | record | release, page 10 | "fourth- quarter 2026" | "fourth-quarter 2026" |
| `r3-p-sens-conditions` | passage | release, page 10 | "fourth- quarter 2026" | "fourth-quarter 2026" |
| `r3-p-unc-vs-estimate` | passage | release, page 4 | "third- quarter 2026" | "third-quarter 2026" |
| `q3-outlook-capex-planned-projects-fy2026` | record | 10-Q, page 25 | "a. Includes" | "a.Includes" |
| `q3-p-smelter-restart` | passage | 10-Q, page 44 | "re- commenced" | "re-commenced" |
| `q3-p-downstream-debt-def` | passage | 10-Q, page 52 | "a. Represents" | "a.Represents" |

The SEC files set a footnote letter and its text in two adjacent elements, spaced by layout, so the page text joins
them ("a.Includes"). The 10-K's page texts, read the same way, do the same.

## What the SEC copies show beyond the PDFs

- **The Bagdad exhibit is three page images.** `fcx_261104.htm` shows `fcx_261104001.jpg` to `fcx_261104003.jpg`
  and carries the release's text in the file, in white 1-point type. That text is what the tool reads and what the
  quotes match. The three images were retained by `fcx-sec-images-02` and compared
  with that text visually (`research/fcx/acquisition/fcx-sec-images-02/visual-check.md`): no difference.
- **Each retained SEC file is 113 bytes larger than the size the EDGAR folder index lists.** The server appended one
  script element after the end of each document. It carries no text, and the page texts do not include it. The SHA-256
  in `sources.json` is that of the complete response, as for the 10-K.
- **The filing dates** are read from the EDGAR submissions record (fcx-sec-locate-02): 2026-11-06 for the 10-Q,
  2026-10-27 and 2026-11-04 for the Forms 8-K. Each equals the date already recorded.

## How to repeat it

From the repository root, with the retained files present:

```text
git show a8c89d6:research/fcx/facts.json > <scratch folder>/facts-before.json
python -I research/fcx/tools/sec_match.py <scratch folder>/facts-before.json --write
```

`a8c89d6` is a commit of the private development repository (not in this one); it holds `facts.json` as it stood on the investor-relations PDFs. The tool reads those PDFs only to compare
pages.
