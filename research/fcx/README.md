# Freeport-McMoRan (FCX): company research, stage 1

Status: **research package, 2026-11-08.** It follows on from the copper thesis and its exposure map
(`docs/copper-exposure-map.md`, `docs/copper-thesis-sources.md`).

- **Who wrote it:** the assistant (Claude).
- **Review:** **all interpretation is an AI draft, not reviewed by the project owner.** Figures are quoted from the
  company's reports and checked by a script; the reading of them is not checked by anyone yet.
- **What it is not:** a page, a valuation, a target price or advice. Valuation is the next stage.

## Purpose

The goal is to learn to analyse one company end to end, and to explain in an interview how the copper sector, the
company's operations and its cash flow connect. The owner's request of 2026-11-08 asked for five parts, plus a page
specification:

| Part | File |
| --- | --- |
| 1. The business: products, regions, key assets, copper exposure | `business.md` |
| 2. The data table: revenues, operating income, operating cash flow, capital expenditure, cash and debt, operating metrics | `data-table.md` (generated from `facts.json`) |
| 3. Period comparisons and what changed: quarter, nine months and year kept apart; consolidated and attributable kept apart | `comparison.md` |
| 4. The mechanism map: copper price, volumes, costs and investment through to cash flow; published sensitivities kept in their own measure | `mechanisms.md` |
| 5. Missing information and follow-up questions | `gaps.md` |
| The company page specification | `page-spec.md` (private; not in the public repository) |
| Stage 2: the Scenarios tab (price × volume, and the published cash flow sensitivity applied linearly) | `scenarios-spec.md` |
| The source package (four documents, including the Bagdad release of 2026-11-04) | `sources.md`, `sources.json`, `acquisition/` |
| The match of every record and passage against the SEC copies (2026-11-11) | `sec-match.md`, `sec-match.json`, from `tools/sec_match.py` |
| Notes from the extraction (definitions, caveats, inconsistencies) | `extraction-notes.md` |
| The company page's texts and tables (generated; the page itself is /companies/fcx) | `page.json`, from `tools/build_page.py` |

## How the numbers are kept honest

- **`facts.json` holds every number.** Each has a unit, a period (with dates), a basis and a kind:
  - **published:** quoted from a retained report, with the document, page, section, row, column and the verbatim
    quote;
  - **computed:** a formula over record ids;
  - **assumption:** what it assumes, which records use it, and which documents its statement describes
    (`rests_on`, empty for a statement of method).
- **Basis:**
  - consolidated;
  - attributable to common stock;
  - noncontrolling interests;
  - net of noncontrolling interests;
  - a company definition (non-GAAP);
  - a named segment, division or mine.
- **`tools/check_facts.py` checks the records.** It confirms:
  - each retained file's SHA-256;
  - that every quote occurs on its stated page;
  - that every printed figure reads as its value;
  - that every computed figure recomputes from its inputs.

  It also refuses a calculation that mixes bases, periods or units unless the record states the mix and why. Every
  record id cited in these documents in backticks must exist.
- **The same figure in two documents must agree.** `facts.json` lists 89 such pairs (release and 10-Q, 10-K and
  release, the Bagdad release and the 10-Q), and the checker compares them.
  - One difference is outside the pairs: the 10-Q shows 2025 operating cash flows $25 million lower than the release.
    Neither document explains it or calls it a restatement. Both figures are kept, and the difference is a computed
    record (`c-ocf-difference-9m-2025`).
- **`tools/render_table.py` writes `data-table.md` from `facts.json`.** A table row may not mix bases.
- **Current size:**
  - 970 published figures (269 from the results release, 364 from the 10-Q, 322 from the 10-K, 15 from the Bagdad
    release);
  - 103 computed figures and 8 assumptions;
  - 214 short passages.

  All were checked against the retained files on 2026-11-08. Two subagents extracted the 10-K and the 10-Q; the lead
  assistant extracted the results release and checked everything (`extraction-notes.md`). The fix round of the same
  day added the company's revenue bridges, the Bagdad records and the passages behind the corrected readings. On
  2026-11-11 the records and passages from the 10-Q and the two releases were matched against the SEC copies of those
  documents (`sec-match.md`).
- **Documents cite records by id**, e.g. `r3-cu-sales-q3-2026`.
  - Prefixes: `r3-` (the Q3 2026 results release), `q3-` (the Q3 2026 10-Q), `k25-` (the 2025 10-K), `nr-` (the
    Bagdad release of 2026-11-04), `c-` (computed) and `a-` (assumptions).

Run from the repository root:

```text
python -I research/fcx/tools/render_table.py
python -I research/fcx/tools/check_facts.py
```

Without the private retained files (`data/company-sources/fcx/`), the checker skips the quote checks and says so.

## Sources in one line

All four are SEC EDGAR copies: the 2025 Form 10-K (signature date 2026-02-13, reused from the copper thesis
acquisition), the Q3 2026 Form 10-Q (signature and filing date 2026-11-06), and the Q3 2026 results release (dateline
2026-10-27) and the Bagdad release (dateline 2026-11-04), each exhibit 99.1 to a Form 8-K of the same day (the
results release furnished under Items 2.02 and 7.01, the Bagdad release attached under Item 8.01).
Details are in `sources.md`.

## Boundaries

- **Within the approvals.** No other data was downloaded. No paid service and no third-party market data were used.
- **No shared changes.** Shared code, `SPEC.md`, `README.md`, `INCLUSION.md`, the copper thesis files and the copper
  calculator are unchanged. Nothing here is served by the app.
  - The calculator still carries the 10-K's Bagdad figures, which the company's November statements supersede. That is
    left to the owner (`gaps.md`, section E).
- **Sensitivities as published.** The company's published sensitivities appear only in its own measure and conditions
  (`mechanisms.md`).
