# Data provenance

Second Order is an economic research tool, not a trading or recommendation tool. This note lists the third-party
material the repository holds, the terms it is held under, and what the repository leaves out.

## What is shipped

- The source code, under the MIT [LICENSE](LICENSE).
- Research content written for the project: event readings, the copper thesis, event chains and publication
  comparisons. They hold short quotations and selected figures, each linked to the document and place it comes from.
- Small extracts that this content and the tests read, listed below.
- Demonstration data: the fictional market series of the offline demo (demo-market-0.1, every number invented), the
  fictional interview and speech test cases, synthetic test values and fictional companies, each marked as such.

## What is not shipped

- **Retained source files.** Each downloaded document is kept under `data/` with its acquisition record, and `data/` is
  not committed. A fresh clone therefore withholds every figure that rests on a retained file until that file is
  acquired again.
- **Working notes.** Dated working logs and design notes that some documents cite (under `docs/`) are kept in the
  private repository.
- **Earlier evidence versions.** The versions that rested on the company's investor-relations copies, their
  acquisition records and the private source notes stay private; the public version numbering of the affected
  comparison and chains starts at the SEC-based version.
- **Local records:** the research store, accounts, the analyst's notes and readings.
- **Keys and credentials.** Keys that appear in tests are dummies.

## Sources and terms

| Source | Used for | Terms |
|---|---|---|
| Board of Governors of the Federal Reserve System (H.15, G.17, FOMC statements) | Treasury yields around events, case readings | Public domain; the Board is cited |
| U.S. Geological Survey, Mineral Commodity Summaries | Mine production, reserves and the annual copper price | U.S. public domain |
| Company filings on SEC EDGAR | Company statements and figures | Public filings |
| BLS, BEA, Census Bureau, EIA, Commerce (BIS), Treasury (OFAC) | Case readings and tests | U.S. public domain |
| International Energy Agency, Critical Minerals Dataset | Copper demand and supply projections | CC BY 4.0. Based on IEA data, © IEA; values selected and, where stated, combined by Second Order |
| European Commission, ECB, WTO | Short excerpts in tests | Reuse with attribution, as each publisher states |

The MIT licence covers the code only. Third-party material stays under its own terms, and no warranty is made about it.
