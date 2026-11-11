# Metals comparison, stages 1 and 2 (implementation note)

Date: 2026-11-05; review fixes 2026-11-06 (SPEC 0.5.31, metals-usgs-0.2, metals-view-0.2); page layout 2026-11-06
(SPEC 0.5.32, presentation only, branch `metals/page-ux`); stage 2, the research layer, 2026-11-06 (SPEC 0.5.33, below).
Branch `metals/comparison-stage-1`; stage 2 is on branch `metals/stage-2` (section "Stage 2: the research layer" below).
Spec: SPEC.md, "Metals (comparison, stage 1)" and "Metals (stage 2: research layer)". Design:
`docs/superpowers/specs/2026-11-05-metals-market-research-design.md` (private; not in the public repository). Read-only: nothing was acquired, fetched or sent
to a model, and nothing is written by the page or the route.

## What it is

The page `/metals` (operator build) lays out two retained files side by side, for the metals a reader picks (the
six defaults copper, lithium, cobalt, rare earths, nickel and aluminum, or `?m=a,b` in the address). It opens on a
short header, a closed picker (one button, "6 of 45", with search, multiple choice, Defaults, Clear and Done inside)
and three tabs whose choice stays in the address's hash: **Overview** (the comparison), **By metal** (one metal at a
time, its parts closed until opened) and **Method & sources** (the notes, this read's source check and the Sources
list). Longer words sit one click away: a "Why?" beside each figure not shown, the years caveat beside each years
figure, "How to read this table" under the comparison's title.

- **The comparison** (Overview), one row per picked metal and 2025 production stage (mine, smelter, refinery and the like, as
  printed; a pick with none gets one row that says so): the largest named producer and its share of the world total
  USGS prints for that stage, the three largest named producers and their combined share, the largest named holder of
  reserves (the reserves series paired with that stage, else the chapter's only 2025 reserves series named by its
  printed detail, else "No matching 2025 reserves series"), and years of reserves "at the 2025 rate; not a depletion
  date". Rankings are among the countries USGS names; "Other countries" is one group USGS does not split, never
  ranked. Where a figure is not shown the cell gives a short label ("Order unknown", "Unit in doubt" and the like)
  and "Why?" opens the full reason.
- **By metal**: the USGS series in closed parts (Production, Reserves, US imports and reliance, Notes in the USGS
  file; Reserves is flagged "Unit in doubt" for vanadium before it is opened), and, for six minerals, the IEA part
  apart: its scope note, then demand by technology and scenario and supply by country, mining and refining apart,
  with the IEA's own top-3 figure, each closed.
- **Plain notes** (Method & sources) on concentration, mining against refining, reserves against resources and
  stocks, years of reserves, by-products and printed codes. They name no metal, company or country and state no price
  direction, forecast, recommendation or cause.
- **Sources** (Method & sources): each file's publisher and title, edition, terms (its licence and note, so the IEA's requested
  citation and "Changes and comparisons here are this project's" appear), state on this read with its detail, and its
  address.

## How it is built

- `second_order/metals_usgs.py` (metals-usgs-0.2; 0.3 with stage 2, whose reliance rows carry their commodity) reads
  the USGS data-release CSV: 45 chapters, the world-table series of each, shares against the printed world total, leader
  and top 3, years of reserves, import sources and reliance, and each series' known unit issue (`UNIT_ISSUES`).
- `second_order/metals_iea.py` (metals-iea-0.1) reads two sheets of the IEA workbook, checking the layout cell by cell.
  Supply shares are to one decimal; `energy_share` and `top3_published` are the workbook's stored values times 100.
- `second_order/metals_view.py` (metals-view-0.2) verifies both files against their acquisition records on every read
  and builds the reply; `metals_api.py` serves `GET /api/metals`. `content/metals/sources.json` holds the two source
  entries.
- `frontend/src/metals.ts` reads the reply fail-closed and recomputes every share, ranking and years figure exactly
  (the same rules as the engines); a mismatch refuses the whole read, naming a place and a rule, never a value. It
  also holds `reservesFor`, which picks the reserves series shown beside a production row from the server's
  years-of-reserves pairs. `MetalsPage.tsx` (header, picker, tabs), `MetalPicker.tsx`, `MetalsCompare.tsx`
  (Overview), `MetalDetail.tsx` (By metal), `MetalsMethod.tsx`, `MetalsBits.tsx` (the shared cells, "Why?", parts and
  tabs), `metalsNotes.ts`, `metalsPicks.ts` (picks, tab hash, search), `metalsWords.ts` (short labels) and
  `metals.css` render it and compute nothing.

Rules that came out of review, now in the code:

- A series with no shares gives every cell's share its no_shares reason, and a series with no country rows says "USGS
  prints no country for this series".
- A years-of-reserves reason comes from the world cell itself (the reserves or production series' own world problem).
- A USGS layout refusal gives one fixed problem text (`metals_view.USGS_LAYOUT_PROBLEM`), because a refusal message
  can carry file labels. An IEA refusal names its cell and rule.
- Every pick gets a comparison row, also when its chapter has no world table or its part is withheld.
- A withheld part shows frames only (names from this code, never from the file). The other part is unaffected, and the
  withheld file's values, words and reasons appear nowhere on the page, hidden text and attributes included.
- A named country printed exactly "—" (after trimming) counts as zero for the order and the combined share of the
  leader and top 3, on the server and in the reader: it never outranks a positive value, ties at zero go by name, and
  its own share stays "Printed as “—”". Every other non-number (W, NA, XX, s, ranges, bounds, words) still withholds
  the order. The leader needs at least 1 named country and the top 3 at least 3.
- A known unit issue is stated, never inferred from a result's size (independent review, 2026-11-06). The data file
  labels vanadium's 2025 reserves "metric tons" (world 21,000, Australia 10,000); the printed vanadium chapter of
  Mineral Commodity Summaries 2026, page 2, heads the same column "thousand metric tons", a factor of 1,000. The
  chapter is not a retained, verified source here (the review's copy sits outside the project), so nothing is
  converted and the CSV is unchanged. `metals_usgs.UNIT_ISSUES` names that series by id with fixed words ("Unit in
  doubt: ..."), the reader holds the same table, and the page shows the words above the table, "unit not shown"
  instead of the unit and "Not shown: unit in doubt" instead of each quantity; the shares and the ranking stay (a
  share divides two figures of the same column), and the years figure is withheld with the same words. To convert
  instead, the chapter must first be retained with an acquisition record (an owner decision).
- The rule that withheld every years figure under one is gone: a valid ratio under one year reads "less than 1"
  ("less than 1 year" on the page). No real chapter has one; the synthetic silver series covers it.
- The reader checks each years pair field by field: a 2025 Reserves series and a 2025 mine Production series of the
  same commodity and unit and the same stage qualifier. It also checks that each series id is made from the series'
  own chapter, statistic, detail, unit and year, and that `unit_issue` is exactly its own table's entry. A reply that
  changes one of those fields is refused even when the division would give the same figure (the review's audit: unit,
  year, statistic and stage, each alone).
- The ranking is qualified everywhere it appears: "Largest named producer", "Three largest named producers" and
  "Largest named reserves holder", a line above the comparison, "Ranked among the countries USGS names" under each
  table with the other-countries group's share, "Other countries (one group, not split by USGS)" as that row's
  label, and the concentration note. On the real file the group holds more than the third named country in 14
  series of 2025 that have a top 3 (copper's mine output, 3,000 against Peru's 2,700; gold's, 1,000 against
  Australia's 280).
- A world total printed as zero has its own reason, "The world total is printed as “0”, so no share can be computed".
- The world cell says whether USGS rounded it (`rounded`, from a detail ending ": rounded" or ", rounded"); the page
  labels it "World total (rounded by USGS)", and the concentration note says a share is of that rounded total, so the
  shares of one series may add up to more or less than 100 (as for zirconium's and vanadium's 2025 mine production).
- The reader also checks each IEA mineral's chapter against the fixed mapping the page joins on, and each withheld
  frame's name and chapter against the constants.

## Sources and terms

- USGS Mineral Commodity Summaries 2026, data release, commodities data file (`MCS2026_Commodities_Data.csv`, edition
  date 2026-02-06). Licence CC0 1.0 (the data release's rights field). Owner download, matched to the item record.
- IEA Critical Minerals Dataset 2026 (`IEA-Critical-Minerals-Dataset-2026.xlsx`). CC BY 4.0; cite as "IEA (2024),
  Critical Minerals Data Explorer, IEA, Paris". Changes and comparisons here are this project's. The IEA's supply
  figures are its base case and its forecasts are its projections, marked as such.

Both are the copper folder's retained files. The scopes differ (the IEA's magnet rare earths against USGS's all rare
earths, lithium content, graphite by grade), so the two are shown apart and never compared.

## What it does not claim

No price view, forecast, balance of supply and demand, cost curve or incentive price of this project's own; no cause for
any concentration; no statement that a metal runs out (years of reserves is a ratio at one year's rate); no ranking of
metals against each other; no stocks. Every number is the file's own, or a share, rank or ratio computed from the
file's own printed total. A figure printed as "W", "NA" or a bound such as ">2,000,000" is shown as printed and never
replaced by a guess. A dash is shown as printed too; it is read as zero only to order countries, as the design reads
"a dash for zero", and is given no share.

## Remaining unknowns

- The USGS code key (W, NA, E, XX, s and the like) is not retained, so a print is shown but not explained; only the
  dash is read, as zero, for the order.
- No stocks, owners, by-products or events yet: stages 2 and 3 of the design.
- Some leaders and top 3s are withheld because a named country is printed W or another non-number (NA, XX, s, a
  range, a bound or a word), so the order is unknown (for example lithium's 2025 mine production, United States, W). A
  dash no longer withholds one: copper's 2025 mine production (Germany "—") now has its leader, Chile 23.0%, and top
  3, Chile, Congo (Kinshasa) and Peru, 48.7%. On the real file, 15 of the 51 series of 2025 production leave their
  leader withheld (8 by a code, 4 with no world total, 3 with no named country).
- Vanadium's 2025 reserves keep their unit issue until the printed chapter is retained and verified; only then can
  the quantities and the years figure be shown, converted with the chapter as their stated source.
- Rankings cover named countries only. "Other countries" cannot be split from this file, so no complete world ranking
  is possible from it.
- Three chapters have no world table: germanium, rare earths (heavy) and thallium. The page says so.
- The IEA covers six minerals; the other chapters have the USGS part only.
- USGS and IEA scopes differ and are not reconciled.

## Stage 2: the research layer

Date: 2026-11-06, review fixes 2026-11-07 (SPEC 0.5.33, then 0.5.34; metals-risk-0.1, metals-iea-uses-0.1,
metals-research-0.1, then 0.2, metals-view-0.3, then 0.4, metals-usgs-0.3; rules unchanged at 0.5.0, store schema 4, accounts store accounts-3). Branch `metals/stage-2`. Plan:
`docs/superpowers/plans/2026-11-06-metals-stage-2.md` (private; not in the public repository). Spec: SPEC.md, "Metals (stage 2: research layer)". Still
read-only: nothing is acquired, fetched or sent to a model, and nothing is written.

### What it adds

For each metal under **By metal**: a **Snapshot**, always open at the top, whose items each name their source (largest
named producer by stage, largest single-country share by stage, largest named reserves holder with years of reserves,
US net import reliance, the critical-minerals mark, a unit issue where there is one, and the IEA's energy-technology
demand for 2025). US net import reliance is the chapter's first 2025 row; where USGS prints more than one 2025 figure
(bauxite and alumina, titanium sponge and pigment, the PGMs, silicon, zinc and others), each figure is named by its
commodity as printed and the headline says it is one of N. Then folds, closed on arrival, in this order: Production and Reserves (stage 1), **Supply chain**,
**Concentration & risk**, **Industrial uses**, **Geopolitical exposure**, **Economic transmission**, US imports, the
USGS notes and, for six minerals, the IEA part. In **Overview**, a **Leaders | Concentration** switch.

- **Supply chain**: the stages USGS prints for 2025, mining then refining, each with its largest named country (CR1)
  and three largest (CR3); a stage the file has no table for is named ("USGS's file has no refining table for this
  metal"), never filled from another; final products always read "no retained source covers this stage"; US import
  dependence and secondary production; possible alternative sources (a comparison of shares, not of capacity); the IEA's
  mining and refining countries in a block of their own; recycling and substitution as quoted.
- **Concentration & risk**: CR1, CR3 and the HHI for each 2025 production and reserves table. The HHI is a range (low
  bound: "Other countries" spread thin; high bound: one holder of all that remains) with the named countries' coverage
  beside it, because USGS does not split "Other countries". The same measures over US import sources. Each indicator
  has an About note: formula, source, year. No composite score.
- **Industrial uses**: the IEA's energy-technology demand by technology (2025, and a scenario and year chosen with
  the part's own selects), each technology's share of 2025, the share of energy technologies in the IEA's total demand
  (six minerals), end uses quoted from retained sources (copper), and a note that industrial importance, strategic
  criticality and supply risk are different things.
- **Geopolitical exposure**: structural indicators only, and events only from a cited passage verified on this read,
  each quoted with its source's title, publisher and edition and its place; otherwise the exact sentence that no
  verified event is retained ("Events appear here only from a retained primary source (an official publication or a
  filing), dated."). A cited passage that is not verified is listed apart, with its reason and no kind.
- **Economic transmission**: assistant-written chains under the fixed "Written by the assistant ... not reviewed by the
  owner" sentence. Each link is labelled Measured (a figure the page already shows, with the coverage beside an HHI),
  Stated by a source (a quote from a retained source, verified on this read) or Hypothesis (neither).

### How it is built

- `second_order/metals_risk.py` (metals-risk-0.1): CR1, CR3, named share, over-total flag and HHI bounds for each 2025
  Production and Reserves series; stages (an export series, such as mercury's "Mine production: exports", is no
  stage), missing stages, whether one country leads mining and refining, the stage with the largest single-country
  share, alternatives (shares of reserves above shares of output), US net import reliance with its commodity, and US
  import-source tables with the same measures. Exact fractions, half to even; a dash counts as zero; any other
  non-number withholds the series with its reason.
- `second_order/metals_iea_uses.py` (metals-iea-uses-0.1): sheets 3.2 and 3.1 of the IEA workbook, checked cell by cell;
  fixed mapping of IEA names to USGS chapters with scope notes; Boron and Total are skipped by name and any other
  unmapped label refuses the part; a technology block must print the mineral row's total.
- `second_order/metals_research.py` (metals-research-0.2) and `content/metals/research.json`: the notes, every link
  one of three kinds, any other shape refusing the whole file; resolved against the figures the page already holds
  and the copper thesis's passages (the only thesis cited), which are checked against their retained sources on every
  read and carry their source's title, publisher, edition and edition date (`thesis_view.passages`), so the page names
  a source, never its id. Each event carries `when`, the date its quote gives, which must be in the verified quote,
  so an event from a past report reads as past, not as news. It computes nothing new.
- `second_order/metals_view.py` (metals-view-0.3, then 0.4 for the dated events): the reply gains `risk`, `uses` and `research`. `risk` is withheld
  with the USGS part; `uses` is read apart from the `iea` part, so its refusal never withholds that part; a withheld
  part holds frames only.
- `frontend/src/metalsStage2.ts` checks each part again from parts already read (every indicator from the series cells
  and import rows, every IEA share from its numbers, every measured link from the reply, every passage's fields held
  to its state); `metalsSections.ts` picks what each section reads; `components/MetalSnapshot.tsx`, `MetalSupply.tsx`,
  `MetalsConcentration.tsx`, `MetalUses.tsx`, `MetalExposure.tsx`, `MetalTransmission.tsx` and `MetalsBlocks.tsx` lay
  it out and compute nothing.

### The browser check

`frontend/tests/browser/metals-check.mjs` (plumbing and the value lists in `metals-kit.mjs`, the page reading in
`metals-stage2.mjs`, the controls in `metals-controls.mjs`, screenshots in `metals-shots.mjs`). Per metal, with every
fold open, it reads the snapshot, supply chain, concentration, uses, exposure and transmission off the page and compares
each with the reply (strings written again from the reply, not from the page's code); it opens every new fold, About
note with real key presses (Enter and Space on each new fold, on copper and cobalt; six About notes on two metals), sets the
uses selects in code, drives the Overview switch from the keyboard, reads the page's own words with every fold open and the
Concentration view shown for the no-recommendation scan, and, with the CSV changed and with the workbook
changed, scans every metal in every tab for the withheld part's figures and words (the risk and uses figures and
words are in the lists) and for any value in research's measured links. The scan leaves out only the page's own fixed
words, each checked apart (link badges, About notes, select options, chain link counts, the new folds' teasers, the
Concentration scope words), the page's own IEA year labels where they stand (year headings, marked year labels,
year-keyed attributes, the year a table frame's name ends with) and one-character values; no year or hand-typed number
is exempt elsewhere, and a negative control proves a year printed as a value in an IEA cell is found. The synthetic server copies the committed
`research.json` beside its synthetic sources, so copper's two cited events stay unverified there ("No verified event is
retained" with both under "Cited, not verified on this read"); on the real files both are verified and quoted.

### What it does not claim (Stage 2)

No final-products stage (no retained source covers it); no uses outside energy technologies except copper's quoted
end uses; no official export-control or sanctions source, so none is shown; events only for copper's two cited
passages; the HHI is a range, never a point estimate; no composite score, no ranking of metals, no price view. The
research notes are assistant-written and have not been reviewed by the owner; their stated links rest on the copper
thesis's retained sources, and a quote that is not verified on this read is withheld, never shown.

## Verification

Page layout (branch `metals/page-ux`, 2026-11-06, in this worktree): `npm test` 536/536; `npx tsc --noEmit` and
`npm run build` exit 0; `npm run test:browser:metals` 61/61 synthetic and 53/53 real (opt-in, retained folder
unchanged); `npm run test:browser:library` 271/271 and `test:browser:thesis` 49/49 (both link to /metals);
`python -m unittest discover -s tests` Ran 2048 tests, OK (skipped=21); `python -m second_order demo` exit 0.
Screenshots (desktop 1280 px and phone 390 px: first screen, picker open, a "Why?" open, By metal, Method) were saved
with `SECOND_ORDER_SCREENSHOTS` to the ignored `data/local-checks/metals-ux-2026-11-06/`.

Stage 2 (branch `metals/stage-2`, 2026-11-06, in the worktree `second-order-v2-metals-stage2`), each command run once, one
at a time, the Python suite not alongside a browser check:

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests` | Ran 2113 tests in 548.536s, OK (skipped=28) |
| `python -m second_order demo` | exit 0 (output to a file; nothing tracked changed) |
| `npm test` (frontend) | 568 tests, 568 pass, 0 fail |
| `npx tsc --noEmit` and `npm run build` (frontend) | exit 0; built |
| `npm run test:browser:metals` (synthetic) | 79/79 checks passed |
| `npm run test:browser:metals` (real, opt-in) | 68/68 checks passed (copper's two events verified and quoted; retained folder unchanged) |
| `npm run test:browser:library` | 271/271 passed (links to /metals) |
| `npm run test:browser:thesis` | 49/49 passed (links to /metals) |

The metals check grew from 61 (synthetic) and 53 (real) to 79 and 68. Screenshots (desktop 1280 px: first screen, picker
open, Overview Concentration view, copper's snapshot, Concentration & risk open, Economic transmission open, Method &
sources; phone 390 px: first screen, picker open, copper's snapshot, copper's transmission) were saved from the real
run with `SECOND_ORDER_SCREENSHOTS` to the ignored `data/local-checks/metals-stage2-2026-11-06/` (never committed).

Stage 2 review fixes (SPEC 0.5.34, metals-research-0.2, metals-view-0.4), run on 2026-11-07 in the worktree
`second-order-v2-metals-stage2`, one command at a time. Before the fixes, the same worktree at 8002ad6 gave `npm test`
573/573 and the synthetic browser check 79/79, as reported. The library and thesis checks were not repeated: no module
those pages import changed.

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests -p "test_metals_*.py"` | OK |
| `test_metals_api.py` with `SECOND_ORDER_THESIS_SOURCES` set | Ran 41 tests, OK (each event's date is in its verified quote) |
| `python -m unittest discover -s tests` | Ran 2123 tests in 667.295s, OK (skipped=32) |
| `python -m second_order demo` | exit 0 (output to a file; nothing tracked changed) |
| `npm test` (frontend) | 574 tests, 574 pass, 0 fail |
| `npx tsc --noEmit` and `npm run build` (frontend) | exit 0; built |
| `npm run test:browser:metals` (synthetic) | 80/80 checks passed (one new: the picker's one-column order) |
| `npm run test:browser:metals` (real, opt-in) | 69/69 checks passed (copper's two events dated, each date in its quote; retained folder unchanged) |

Screenshots of the real run (desktop and phone, with copper's uses on desktop and its events on phone added) were saved
outside the repository.

Review fixes, run on 2026-11-06 in this worktree, one command at a time, after the review fixes (the thesis and copper-tools rows are
from 2026-11-05, not repeated: the fixes change no module those pages import and no file their routes read).

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests -p "test_metals_*.py"` | Ran 56 tests, OK (skipped=10: the opt-in real class) |
| the same, `RealSources` with `SECOND_ORDER_THESIS_SOURCES` set | Ran 10 tests, OK |
| `python -m unittest discover -s tests` | Ran 2048 tests in 617.888s, OK (skipped=21) |
| `python -m second_order demo` | exit 0 (output to a file; nothing tracked changed) |
| `npm test` (frontend) | 529 tests, 529 pass, 0 fail |
| `npx tsc --noEmit` and `npm run build` (frontend) | exit 0; built |
| `npm run test:browser:metals` (synthetic) | 58/58 checks passed |
| `npm run test:browser:thesis` (synthetic, 2026-11-05) | 49/49 passed |
| `npm run test:browser:copper-tools` (synthetic, 2026-11-05) | 38/38 checks passed |
| `npm run test:browser:metals` (real, opt-in) | 48/48 checks passed; cobalt 74.2%, lithium top-3 reason naming the United States and "W", copper 43 years, copper's mine leader Chile 23.0% and top 3 48.7%, vanadium's reserves flagged (no quantity or unit shown, shares kept, years withheld with the issue's words), the named-country headings and table feet; retained folder unchanged |
| `npm run test:browser:thesis` (real, opt-in, 2026-11-05) | 35/35 passed |
| `npm run test:browser:copper-tools` (real, opt-in, 2026-11-05) | 36/36 checks passed |

The real runs used `SECOND_ORDER_THESIS_SOURCES=<checkout>/data/sector-sources/copper`,
read-only; each check proves that folder unchanged. The counts differ between the synthetic and real runs because some
steps run on one kind only (for metals, the byte-change withholding steps are synthetic-only and the real values are
real-only).
