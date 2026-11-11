# FCX stage 1: source package

Four documents, all SEC EDGAR copies, retained privately under `data/company-sources/fcx/` (ignored by Git). The
machine-readable manifest is `sources.json`, and the request records are in `acquisition/`. `tools/check_facts.py`
checks each file's SHA-256 before it reads a quote, and the page server checks each file against its acquisition
record on every read.

The 10-Q and the two releases were first read from copies on the company's investor-relations host. On 2026-11-11
every record and passage resting on them was matched against the SEC copies (`sec-match.md`): 749 exact, 6 that
differed only in spacing, none relaid, none not found, no definition changed. The package now reads only the SEC
copies. The earlier copies and how they were obtained are described in
`sources-private.md` (private; not in the public repository).

## The documents

Each date is given with the kind of date it is.

| Id | Document | Period | Date, and what kind of date | SEC accession and address | Retrieved | Size, SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| `10k-2025` | Form 10-K, fiscal year 2025 | year ended 2025-12-31 | 2026-02-13: signature date (page S-1). The EDGAR file's Last-Modified header is the same day; the filing index was not read. | 0000831259-26-000012: https://www.sec.gov/Archives/edgar/data/831259/000083125926000012/fcx-20251231.htm | 2026-11-02 19:25 +02:00 (copper-sec-01, reused) | 6,347,587 bytes, `7ba50efcd0e7…` |
| `10q-2026q3` | Form 10-Q, third quarter 2026 | quarter and nine months ended 2026-09-30 | 2026-11-06: signature date (page S-1). The EDGAR filing date is the same day. | 0000831259-26-000051: https://www.sec.gov/Archives/edgar/data/831259/000083125926000051/fcx-20260930.htm | 2026-11-11 00:40 +02:00 (fcx-sec-docs-02 n=1) | 4,013,452 bytes, `d2ddefc6b0b0…` |
| `release-2026q3` | News release "Freeport Reports Third-Quarter and Nine-Month 2026 Results", with supplemental schedules: exhibit 99.1 to the Form 8-K of 2026-10-27 | quarter and nine months ended 2026-09-30, plus outlook for 2026 | 2026-10-27: Date of Report on the 8-K cover, and the release's dateline (page 2). The EDGAR filing date is the same day. | 0000831259-26-000045: https://www.sec.gov/Archives/edgar/data/831259/000083125926000045/a3q2026exhibit991.htm | 2026-11-11 00:40 +02:00 (fcx-sec-docs-02 n=3) | 2,749,156 bytes, `eb2ea32b516d…` |
| `news-2026-11-04` | News release "Freeport Announces Plans to Boost U.S. Copper & Molybdenum Production" (the Bagdad expansion): exhibit 99.1 to the Form 8-K of 2026-11-04 | the announcement of 2026-11-04 | 2026-11-04: Date of Report on the 8-K cover, and the release's dateline (page 1). The EDGAR filing date is the same day. | 0000831259-26-000048: https://www.sec.gov/Archives/edgar/data/831259/000083125926000048/fcx_261104.htm | 2026-11-11 00:41 +02:00 (fcx-sec-docs-02 n=5) | 11,122 bytes, `8ebacd153440…` |

`sources.json` holds the full hashes. Each Form 8-K's cover document is retained beside its exhibit (fcx-sec-docs-02
n=2 and n=4). The cover gives the Date of Report and lists the release as exhibit 99.1.

Pages are cited as printed:

- **10-K:** body pages 1 to 189.
- **10-Q:** body pages, plus S-1.
- **Results release:** pages 1 to 12, then supplemental schedules I to XXVIII.
- **Bagdad release:** pages 1 to 3.

`facts.json` also records the file page that the checker uses. Each file is split at its HTML page breaks
(`tools/source_text.py`).

Two things about the SEC files:

- **The Bagdad exhibit shows its three pages as images.** The file carries the release's text in white 1-point type;
  that text is what is read and quoted. The three images were retained by `fcx-sec-images-02` and compared with the
  text layer page by page (`research/fcx/acquisition/fcx-sec-images-02/visual-check.md`): no difference.
- **Each retained file is the complete response.** It is 113 bytes larger than the size the EDGAR folder index lists,
  because the server appended one script element after the document. That element carries no text.

## How they were obtained

### The annual report, `copper-sec-01`

The same 10-K was retained from the SEC on 2026-11-02 for the copper thesis (approval `copper-sec-01`). That request
declared the owner's contact in the User-Agent, as the SEC asks, and the contact is written nowhere. It was
byte-copied here, and its SHA-256 equals the original record's. It was not requested again.

### The quarterly report and the two releases: `fcx-sec-locate-02`, `fcx-sec-index-02`, `fcx-sec-docs-02`

- **The owner's approval of 2026-11-10:** obtain the SEC EDGAR copies of the third-quarter 2026 Form 10-Q and of the
  two releases, if they were filed as 8-K exhibits, with the metadata needed to locate and verify them, and with no
  paid calls.
- **Four steps, one GET per resource** (each folder holds its `plan.json`, `acquire.py`, and the attempt and outcome
  records):
  1. **`fcx-sec-locate-02`:** the SEC's submissions record for Freeport-McMoRan Inc. (CIK 0000831259). It located:
     - the Form 10-Q for the period 2026-09-30, accession 0000831259-26-000051, filed 2026-11-06;
     - a Form 8-K of 2026-10-27 (items 2.02, 7.01 and 9.01), accession 0000831259-26-000045, filed the same day;
     - a Form 8-K of 2026-11-04 (items 8.01 and 9.01), accession 0000831259-26-000048, filed the same day.
  2. **`fcx-sec-index-02`:** the EDGAR folder index of each of the three filings, which names their documents.
  3. **`fcx-sec-docs-02`:** the 10-Q's primary document, and each 8-K's cover document and exhibit 99.1.
  4. **`fcx-sec-images-02`:** the three page images of the Bagdad exhibit (three requests), retained beside the exhibit
     and compared with its text layer.
- **Every request** declared a contact in the User-Agent, read at request time from the user-level
  `SECOND_ORDER_FEED_CONTACT` and written nowhere. There was a two-second pause between requests. All twelve returned
  HTTP 200 with the complete body.
- **Retained** under `data/company-sources/fcx/`:
  - `sec-edgar-meta/`: the submissions record and the three folder indexes;
  - `sec-10q-2026q3/`, `sec-8k-2026-10-27/` and `sec-8k-2026-11-04/`: the documents.
- **No paid service** was used, and no third-party data (prices, estimates, transcripts).

## Access rules

- **SEC EDGAR** (https://www.sec.gov/os/accessing-edgar-data): public filings. Automated access must declare a contact
  in the User-Agent and stay below ten requests per second.

## Not collected

- **The Q3 2026 conference-call slides.** The 8-K of 2026-10-27 furnishes them as exhibit 99.2 (`fcx3q26cc_final.htm`
  in its folder index); they were not retained. The webcast was not collected either.
- **Earlier quarterly reports for 2026** (Q1 and Q2) and earlier releases.
- **Any market data:** share price, consensus, copper prices beyond those the company states.
