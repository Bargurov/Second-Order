# Copper thesis: sources, terms and decisions

Recon of 2026-11-02. Reading only: landing, catalogue, terms and filing-index pages were read; no data file was
downloaded. Terms must be re-read at acquisition. Quotes are at most 15 words; they were read through a page-summary
tool, so check each against its page before relying on it. Retained files live at
`data/sector-sources/copper/<folder>/<name>`; the folder name is the source id in the thesis file.

## Resources

| Source id (folder) | Address | Format | Edition and date | Terms as read (page) | Decision |
| --- | --- | --- | --- | --- | --- |
| `worldbank` | https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx | XLSX (served as OOXML spreadsheet; the page labels it "XLS") | October 2026 edition, file dated 2026-10-02 | "may not be redistributed or reused without the consent of the original data provider" (third-party exception; https://data.worldbank.org/summary-terms-of-use). Default is CC BY 4.0. | Use, conditional. No copper-specific restriction was found on any readable page. The workbook's own notes sheet could not be read without downloading it; read it right after retention. A restriction covering copper means drop the Pink Sheet and use the USGS annual average price. |
| `worldbank` (terms) | https://data.worldbank.org/summary-terms-of-use | HTML | read 2026-11-02 | as above | Use (retain as the terms record). |
| `worldbank-cmo-2026-10` | https://thedocs.worldbank.org/en/doc/2ac43f46629cf90c2ea5b8929a343593-0050012026/related/CMO-October-2026-Forecasts.pdf | PDF only | October 2026 (press release 2026-10-28; next April 2027) | No file-level terms found; the same general World Bank terms apply. | Use as a PDF, with a transcribed figure bound to the PDF's SHA-256. The charts-and-data ZIP is not requested (format outside html/xlsx/csv/pdf). If the PDF carries a restriction on republishing, "where this view differs" quotes balance outlooks only and says no price forecast is quoted. |
| `usgs-2026` | https://pubs.usgs.gov/periodicals/mcs2026/mcs2026-copper.pdf | PDF | Mineral Commodity Summaries 2026, 2026-02-05 (catalogue lists version 1.1, March 2026) | "considered to be in the U.S. Public Domain" (https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) | Use the chapter PDF. The data release (DOI 10.5066/P1WKQ63T, CSV tables, CC0) is real, but its ScienceBase pages are behind a bot challenge, so no CSV address could be pinned. |
| `usgs-2025` | https://pubs.usgs.gov/periodicals/mcs2025/mcs2025-copper.pdf | PDF | Mineral Commodity Summaries 2025, 2025-01-31 | as above | Use the chapter PDF (previous edition for status). |
| `iea-2021` | https://www.iea.org/files/ffd2a83b-8c30-4e9d-980a-52b6d9a86fdc/TheRoleofCriticalMineralsinCleanEnergyTransitions.pdf | PDF (about 4.9 MB) | 2021 report | "available under the Creative Commons Attribution 4.0 license" (dataset page; the report page states CC BY 4.0). Third-party components are not licensed by the IEA (https://www.iea.org/terms/creative-commons-cc-licenses). | Use by one GET. The 53.2 vs 22.3 kg figures were not seen on the report page and must be located in the PDF after retention. If the GET returns a challenge or bot page, switch to an owner download. |
| `iea-dataset-2026` | https://www.iea.org/data-and-statistics/data-product/critical-minerals-dataset | Download button after sign-in; format not stated | July 2026 (listed Latest) | "available under the Creative Commons Attribution 4.0 license (CC BY 4.0)" (same page) | Owner download into `data/sector-sources/copper/inbox/`. |
| `iea-dataset-2025` | same page | as above | May 2025 (listed Past, no link) | as above | Owner download if the page still offers it; unconfirmed. If not obtainable, reasons that need it read unavailable. **Superseded (2026-11-03):** the owner reported the IEA site does not offer it; not retained. IEA-based reasons compare two years within the 2026 edition (ruling R12). |
| `sec-fcx-2025` / `sec-fcx-2024` | https://www.sec.gov/Archives/edgar/data/831259/000083125926000012/fcx-20251231.htm ; https://www.sec.gov/Archives/edgar/data/831259/000083125925000006/fcx-20241231.htm | HTML | 10-K fiscal 2025 (filed 2026-02-13) and fiscal 2024 | EDGAR public; User-Agent with a declared contact | Use. |
| `sec-scco-2025` / `sec-scco-2024` | https://www.sec.gov/Archives/edgar/data/1001838/000110465926021492/scco-20251231x10k.htm ; https://www.sec.gov/Archives/edgar/data/1001838/000155837025002017/scco-20241231x10k.htm | HTML | 10-K fiscal 2025 (filed about 2026-02-27) and fiscal 2024 (filed 2025-03-03) | as above | Use. |
| `sec-mli-2025` / `sec-mli-2024` | https://www.sec.gov/Archives/edgar/data/89439/000008943926000008/mli-20251227.htm ; https://www.sec.gov/Archives/edgar/data/89439/000008943925000010/mli-20241228.htm | HTML | 10-K fiscal 2025 (year ended 2025-12-27) and fiscal 2024 (filed 2025-02-26) | as above | Use. |
| `sec-tsla-2025` / `sec-tsla-2024` | https://www.sec.gov/Archives/edgar/data/1318605/000162828026003952/tsla-20251231.htm ; https://www.sec.gov/Archives/edgar/data/1318605/000162828025003063/tsla-20241231.htm | HTML | 10-K fiscal 2025 and fiscal 2024 (a separate 10-K/A with Part III exists and is not requested) | as above | Use. |

The eight filing addresses come from search results; no request was sent to sec.gov in this recon, so a not-found at
acquisition is possible and would be recorded as a failed resource.

## Settled points

- **Pink Sheet terms for copper.** Not restricted on any readable page; the third-party exception is general. Use, with
  the notes-sheet check after retention and the USGS price as fallback. **Superseded at authoring:** the workbook's
  Description sheet names third-party sources for copper, so the series is not used (see "Decisions at authoring").
- **Commodity Markets Outlook forecast table.** Only a PDF exists (plus a ZIP of unknown contents). Retain the PDF and
  cite by transcription.
- **EV demand.** Derived from the IEA Critical Minerals Dataset's EV copper demand. No separate EV-sales source in
  version 1.
- **Company set.** In: Freeport-McMoRan and Southern Copper (producers), Mueller Industries (consumer), Tesla (EV maker).
- **IEA 2021 report.** One GET; the PDF address responded normally to a headers-only check, so a challenge is not
  expected. Owner download is the fallback.
- **IEA dataset third-party flags.** Not determinable from any page. The dataset page names none and says the figures
  follow the IEA Global Energy and Climate model; the flags are read from the workbook after the owner downloads it,
  and any flagged series is never cited.
- **Ember.** Not acquired in version 1.

## Not included

- **Codelco.** Its terms allow personal, educational or non-profit use and bar commercial or advertising use ("no puede
  ser utilizada con fines comerciales ni publicitarios por ningún motivo"; https://www.codelco.com/terminos-y-condiciones).
  Reuse in a research view is not clearly covered, so it is left out.
- **Prysmian.** Its legal notes grant copying "for personal use only" (https://www.prysmian.com/en/legal-notes); not
  included.
- **Ember electricity data.** Optional in the design; not acquired.
- **Excluded by design:** IEA Global EV Outlook data and Energy and AI dataset, LBMA/LME/CME prices, ICSG, Silver
  Institute, IMF-sourced series.


## Acquisition outcomes (2026-11-02)

Owner approval in chat, 2026-11-02: "הבנק העולמי (3 קבצים),USGS (2 קבצי PDF),דוח IEA מ-2021 (PDF אחד),SEC (8 דוחות שנתיים)"
(the World Bank 3 files, USGS 2 PDF files, the 2021 IEA report as 1 PDF, the SEC 8 annual reports). One GET per
address, no redirects, no retries; 14 requests sent, 14 complete. Every retained file verifies against its record with
`thesis_sources.verify`. The eight SEC requests carried a declared contact in the User-Agent; the contact is written
nowhere.

| Approval | n | Retained file | Status | Size | SHA-256 (first 12) |
| --- | --- | --- | --- | --- | --- |
| `copper-worldbank-01` | 1 | `worldbank/CMO-Historical-Data-Monthly.xlsx` | complete (HTTP 200) | 586,099 bytes | `ea1c35082787` |
| `copper-worldbank-01` | 2 | `worldbank/summary-terms-of-use.html` | complete (HTTP 200) | 207,424 bytes | `3826b1a2d76b` |
| `copper-worldbank-01` | 3 | `worldbank-cmo-2026-10/CMO-October-2026-Forecasts.pdf` | complete (HTTP 200) | 88,063 bytes | `2397f5f87d09` |
| `copper-usgs-01` | 1 | `usgs-2026/mcs2026-copper.pdf` | complete (HTTP 200) | 141,602 bytes | `c4971f7edfa3` |
| `copper-usgs-01` | 2 | `usgs-2025/mcs2025-copper.pdf` | complete (HTTP 200) | 746,302 bytes | `348b1e224d83` |
| `copper-iea-2021-01` | 1 | `iea-2021/TheRoleofCriticalMineralsinCleanEnergyTransitions.pdf` | complete (HTTP 200) | 4,907,491 bytes | `256380dc01c4` |
| `copper-sec-01` | 1 | `sec-fcx-2025/fcx-20251231.htm` | complete (HTTP 200) | 6,347,587 bytes | `7ba50efcd0e7` |
| `copper-sec-01` | 2 | `sec-fcx-2024/fcx-20241231.htm` | complete (HTTP 200) | 6,548,029 bytes | `220349384034` |
| `copper-sec-01` | 3 | `sec-scco-2025/scco-20251231x10k.htm` | complete (HTTP 200) | 10,718,275 bytes | `6340956e768c` |
| `copper-sec-01` | 4 | `sec-scco-2024/scco-20241231x10k.htm` | complete (HTTP 200) | 10,316,965 bytes | `d365418aeb44` |
| `copper-sec-01` | 5 | `sec-mli-2025/mli-20251227.htm` | complete (HTTP 200) | 2,590,366 bytes | `b1580450b26f` |
| `copper-sec-01` | 6 | `sec-mli-2024/mli-20241228.htm` | complete (HTTP 200) | 2,632,798 bytes | `7e602e98d1fc` |
| `copper-sec-01` | 7 | `sec-tsla-2025/tsla-20251231.htm` | complete (HTTP 200) | 2,391,638 bytes | `6613b0ffabe8` |
| `copper-sec-01` | 8 | `sec-tsla-2024/tsla-20241231.htm` | complete (HTTP 200) | 2,596,568 bytes | `8e920d2c97ff` |

Notes read after retention:

- IEA 2021 PDF: the body starts with `%PDF-1.7`, so it is a real PDF, not a challenge page. Corrected at authoring:
  the 53.2 vs 22.3 kg figures are not printed in it (they appear only as unlabelled chart bars), and its page 2 states
  "All rights reserved" and that the publication "is subject to specific restrictions that limit its use and
  distribution". It is not cited.
- Pink Sheet: the workbook's sheets are Mismatch Details, Monthly Prices, Monthly Indices, Description and Index
  Weights. The Description sheet lists the copper series ("Copper (LME), grade A") with its definition. Corrected at
  authoring: the sheet's Sources column for copper is not blank. Cell T89 names "Bloomberg Finance L.P.; Engineering and
  Mining Journal; Platts Metals Week; Thomson Reuters Datastream; World Bank", and the retained terms (paragraph 43) say
  third-party data "may not be redistributed or reused without the consent of the original data provider". The copper
  series is not used (decisions below).

## Owner downloads

| Approval | Status |
| --- | --- |
| `copper-iea-dataset-01` (IEA Critical Minerals Dataset 2026 and 2025, xlsx) | Pending the owner; `acquire.py` written, inbox empty; no request by Claude. |
| `copper-usgs-csv-01` (USGS MCS 2026 data release doi 10.5066/P1WKQ63T: `MCS2026_Commodities_Data.csv`, 3,189,010 bytes, MD5 `36185ff3742087e1dd90c52fe634fe12`, CC0, per the item record the owner pasted on 2026-11-03; MCS 2025 doi 10.5066/P13XCP3R: the copper child item's `mcs2025-coppe_salient.csv`, 783 bytes, MD5 `430a4608f9f69e7a117adc1483a52646`, per the item record the owner saved on 2026-11-03. That item has no world-production file; the 2025 world figures exist only inside the parent's zip archive, so they are read from the retained `usgs-2025` chapter PDF where needed) | Pending the owner (the owner chose to download them; ruling R11); `acquire.py` records each file only when its size and MD5 match the published record; inbox empty; no request by Claude (Claude's ScienceBase reads return HTTP 403). |

**Superseded (2026-11-03):** both owner downloads have since arrived and are recorded. `copper-iea-dataset-01` n=1 is
`iea-dataset-2026/IEA-Critical-Minerals-Dataset-2026.xlsx`; the 2025 edition is not offered. `copper-usgs-csv-01` n=1
and n=2 are `usgs-csv-2026/MCS2026_Commodities_Data.csv` and `usgs-csv-2025/mcs2025-coppe_salient.csv`, each matching
its published size and MD5.

## Decisions at authoring (version 1, 2026-11-03)

- **Pink Sheet copper series: not used.** Re-read with the project's readers before use. The workbook's Description
  sheet describes the series as "Copper (LME), grade A, minimum 99.9935% purity, cathodes and wire bar shapes,
  settlement price" (cell B89), and its Sources column for that row (cell T89) names "Bloomberg Finance L.P.;
  Engineering and Mining Journal; Platts Metals Week; Thomson Reuters Datastream; World Bank". The retained summary
  terms (paragraph 43) say that datasets and indicators provided by third parties "may not be redistributed or reused
  without the consent of the original data provider". The copper series is a third-party LME price, so it is dropped,
  as the design requires.
- **Price record: the USGS producer cathode annual average.** The price record uses the MCS 2026 data release row
  "Price, annual average, cents per pound: U.S. producer, cathode (COMEX + premium)" for 2025 (490, marked
  "Estimated."), in US cents per pound (ruling R18). Opening and latest are that one figure, the only annual figure at
  the opening date. The LME and COMEX rows of the same release are not used, because the design excludes exchange
  prices as sources; the World Bank Commodity Markets Outlook's 2024 and 2025 copper averages are not used either,
  because they rest on the same third-party LME series. That outlook is quoted only for its own forecast columns, as
  the World Bank's labelled expectation.
- **PDF figures and passages were read from the text layer.** Every figure and passage cited from a PDF (the two USGS
  chapters and the Commodity Markets Outlook pages) was transcribed from the PDF's text layer, with line breaks read as
  spaces. No page image was rendered: this machine has no PDF page renderer. Figures that the MCS 2026 data release
  holds are cited from the CSV, not the chapter PDF. One PDF figure remains: the World Bank's 2026 copper expectation.
  The chapters supply passages only.
- **One vintage where the latest edition restates the earlier year (ruling R19).** Two measures now compare 2024 with
  2025 within the MCS 2026 data release: world mine production and US old-scrap recovery. They no longer compare a
  new-year estimate with the previous edition's figure. The release revises 2024 old scrap to 140 kt, from the 150,000
  tons of the 2025 chapter, and the page says so. As a result `usgs-csv-2025` is no longer cited and is removed from the
  sources, and `usgs-2025` keeps only page 1 (passages). Company guidance still compares two editions, because each
  10-K gives one forward year.
- **Estimates are marked.** Every MCS 2026 figure whose Notes cell reads "Estimated." says so in its measure. The
  opt-in test checks the Notes and Unit cells.
- **No computed balance.** The United States refined table is side by side: output, reported consumption, refined
  imports and exports, and yearend stocks. The United States meets the difference through trade and stocks, so a
  "deficit" would misread one importing country as a world shortage. No retained publication gives both sides on one
  world basis, so the content minimum "one computed balance table" is short.
- **IEA attribution.** The Notice sheet asks for the citation "IEA (2024), Critical Minerals Data Explorer, IEA, Paris"
  (its contact address is not copied). Changes in percent and other comparisons on the page are computed by this
  project from the IEA figures, not by the IEA. Both points are in the source's terms note.
- **Commodity Markets Outlook.** The two retained pages carry no copyright or licence statement. The World Bank data
  terms govern its datasets, not this publication. The page quotes only the World Bank's own forecast columns
  ("Source: World Bank."; "f = forecast"), labelled as its forecast. An October forecast for the current year includes
  months already realised.
- **Edition dates are the dates the publishers state (ruling R16).** For the 10-Ks, it is the date in the signature
  block. For the MCS chapters and the Commodity Markets Outlook, it is the first day of the month their footer or header
  states. For the two USGS data releases, it is the publication date in their item records. The IEA workbook states
  only the edition year, so its date is the first day of that year.
- **IEA dataset third-party flags: none.** All twelve sheets of the 2026 workbook were re-read. The Notice sheet states
  CC BY 4.0. The two cited sheets (1 and 2) carry only methodological notes, and no sheet flags a third-party series.
- **IEA 2021 report: not cited.** The retained PDF (revised version, March 2022) states on page 2 that it "is subject to
  specific restrictions that limit its use and distribution" and "All rights reserved". Its copper-per-vehicle figures
  are bars in a chart whose values are not printed in the PDF, so they cannot be transcribed. The computed electric-car
  exposure row is therefore not in version 1.

## Retained files version 1 cites

| Source id | Retained file | What it supplies |
| --- | --- | --- |
| `iea-dataset-2026` | `iea-dataset-2026/IEA-Critical-Minerals-Dataset-2026.xlsx` | Demand by use and scenario (sheet 1); base-case mine and refined supply (sheet 2) |
| `usgs-csv-2026` | `usgs-csv-2026/MCS2026_Commodities_Data.csv` | World mine production 2024–2025; US refinery output (with primary and secondary), reported consumption, refined imports and exports, yearend stocks and old-scrap recovery, 2024–2025; the price record (U.S. producer cathode annual average, 2025) |
| `usgs-2026` | `usgs-2026/mcs2026-copper.pdf` | Passages: end uses, recycling, scrap share and its definition, 2025 mine events, substitutes (text layer, pages 1–2) |
| `usgs-2025` | `usgs-2025/mcs2025-copper.pdf` | Passages: recycling in 2024 and the scrap share (text layer, page 1) |
| `worldbank-cmo-2026-10` | `worldbank-cmo-2026-10/CMO-October-2026-Forecasts.pdf` | Table 1 copper row, forecast columns only: the World Bank's 2026 expectation, quoted with its label (text layer, page 2) |
| `sec-fcx-2025`, `sec-fcx-2024` | the two Freeport-McMoRan 10-Ks | Cash-flow sensitivity and its assumptions; PTFI sales expectations and deferral; the mud rush incident; China as the largest consumer of refined copper |
| `sec-scco-2025`, `sec-scco-2024` | the two Southern Copper 10-Ks | Expected copper production for the year ahead (with its review caveat); copper share of sales |
| `sec-mli-2025`, `sec-mli-2024` | the two Mueller Industries 10-Ks | Pass-through of raw material costs; spreads and FIFO margins; selling-price effect on net sales; aluminium as a substitution threat |
| `sec-tsla-2025`, `sec-tsla-2024` | the two Tesla 10-Ks | Consumer vehicle deliveries |

Retained but not cited: `worldbank/CMO-Historical-Data-Monthly.xlsx` (decision above),
`worldbank/summary-terms-of-use.html` (read for the decision above),
`iea-2021/TheRoleofCriticalMineralsinCleanEnergyTransitions.pdf` (decision above) and
`usgs-csv-2025/mcs2025-coppe_salient.csv` (ruling R19 above).
