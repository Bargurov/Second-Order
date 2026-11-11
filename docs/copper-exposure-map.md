# Copper thesis: the exposure map (implementation note)

Date: 2026-11-04. Branch `thesis/exposure-map`. Presentation only: the thesis API, its source checks, the published
version files and every backend module are unchanged. Nothing was acquired, fetched or sent to a model.

## What it is

Section 8 of the thesis page ("Who is exposed") now opens with a map, ahead of the two exposure tables, which stay as
they were:

- **Plain notes** on three ideas: incidence (who finally bears a cost), pass-through (selling prices following input
  costs, and why that alone does not keep profit unchanged: timing, the spread, inventory accounting such as FIFO) and
  operating exposure (a share of sales and a sensitivity answer different questions).
- **One lane per company the thesis moves.** Each lane starts from a change in the copper price, whatever its cause, and
  shows the stages of its side. A producer's stages are revenue, margin and operating cash flow. A user's stages are
  input cost, its own selling prices, margin and operating cash flow. Each stage is its own box with its own condition,
  so revenue, input cost, margin and cash flow are never merged. Under the stages is what the company's filing states,
  with its served status. The stated figure comes with its metric exactly as served (Freeport-McMoRan: a change in
  operating cash flows per ten cents a pound; Southern Copper: copper's share of sales). The reader can open every
  figure and passage the statement cites.
- **One line per company that moves a reason.** A company's figure is the reason's measure when the ids it cites
  include the reason's latest measured figure (copper v1: Southern Copper's guidance). Otherwise the company is related
  to the reason but does not measure it (Freeport-McMoRan, Tesla): one company's result is not a market measure.
- **Three kinds of line**, each named in words in a legend: solid lines for what a source states, dashed lines for a
  conditional mechanism (general economics, not measured for that company), dotted lines for what is not measured.
  Lines carry no arrowheads. The lead says the thesis does not claim that the physical balance moves the price.

## How it is built

`frontend/src/thesisExposureMap.ts` reads only the reply's structured fields: each company's side, the reason it
moves, the ids it cites, the reason's measured figures, and each part's state. It names no company and reads no
wording to decide a link. It computes no number: stated figures, computed amounts and statuses are shown as served.
The words for stages, lines and concepts are general economics, the same for every company.

`ThesisExposureMap.tsx` renders the map. `ThesisExposure.tsx` holds the section, moved unchanged out of
`ThesisSections.tsx`, which now exports the shared parts the two files use. Styles are in `thesis.css`.

**Source state.** A part the server withholds gives the map its frame only: company, side and stages, or the reason
it names with that reason's title as served (null when the title states a figure). It never shows the part's
statement, figure, metric, status or anything to inspect. Accessible names come from the frame only.

## Remaining unknowns

- **Where each stated figure sits in the accounts is not structured.** thesis-0.1 has no field saying whether a
  figure measures revenue, cost, margin or cash flow. So the map names the filing's metric beside the stages and does
  not place it on one. Placing it would need an authored, cited field in a later thesis version, which is a schema
  change and out of scope here.
- **Mueller.** No pass-through share, lag, margin effect or cash-flow effect is known. Its filings say costs are
  "generally" passed through and that FIFO margins "may be impacted", with no size.
- **Freeport-McMoRan.** The sensitivity rests on the company's own assumptions (an average of $5.00 a pound, current
  volumes and cost estimates). It is a change in operating cash flows. It is not EBITDA, earnings or a share-price
  sensitivity, and none of those is retained.
- **Southern Copper.** A 74.8% copper share of sales says nothing about how much its profit moves with the price. No
  retained sensitivity exists for it.
- **Tesla.** No copper content per vehicle and no copper cost are retained. Its deliveries are related to the
  electric-vehicle reason and are not that reason's measure.
- **No incidence is measured.** Who finally bears a change in the copper price is explained, not quantified, for every
  company.
- The thesis's AI-written interpretation is unchanged and still marked not reviewed.

## Verification

- `npm test`: 479 tests, including 12 in `tests/thesisExposureMap.test.ts`. Four deliberate mutations of the map's
  rules were each caught.
- `npm run build`, run in the worktree, never in a served folder.
- `npm run test:browser:thesis-map`: 33/33 synthetic. This includes a removed source (sec-producer-2025) and a changed
  retained file (sec-maker-2025). In both cases the affected lanes and lines are withheld, and none of the withheld
  facts appears in the page's text, attributes or accessible names. With the real retained sources (opt-in, read-only)
  the result is 25/25.
- `npm run test:browser:thesis`: 49/49 synthetic and 35/35 real, unchanged.
- `python -m unittest discover -s tests`: 1,876 tests OK (7 skipped). `python -m second_order demo` exits 0 (two
  showcase dossiers). AGENTS.md requires both.
