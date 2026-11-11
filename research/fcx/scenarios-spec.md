# FCX stage 2: the Scenarios tab (short spec)

Approved by the owner on 2026-11-08 ("stage 2 of FCX: a learning scenario layer"). Goal: change the company's
assumptions and see what changes in the arithmetic, to explain the company in an interview. Built on the verified
research (`facts.json`) and the integrated page (c898747). Not merged or pushed with this branch.

## What it is

A Scenarios tab on /companies/fcx, after Mechanisms, with two separate calculations. They share no input and are never
added together.

1. **Copper price and volume sold.** Base: the company's assumptions for Q4 2026 in the results release of
   27 October 2026: the copper price `r3-out-cu-price-q4-2026` (added in this stage, quoted from page 10) and the
   expected copper sales `r3-out-cu-sales-q4-2026` (page 3). Inputs: a copper price in US dollars per pound, and copper
   sold in million pounds (sales, not production). Results:
   - sales value S = P × V (US dollars per pound × million pounds = US$ million);
   - the change against the same arithmetic at the company's assumptions, B = P₀ × V₀
     (`c-q4-cu-sales-value-base`);
   - the change split in one fixed order (the research's own convention, `a-price-volume-split`): volume effect
     (V − V₀) × P₀, price effect (P − P₀) × V. The two add up to S − B exactly; another order would split it
     differently.
   The definition sits beside the result: an approximate value of copper sales under these assumptions, not reported
   revenue, earnings or cash flow (`a-scenario-sales-value`).
2. **The company's published cash flow sensitivity.** Only the copper sensitivity in the October release,
   `r3-sens-ocf-copper`: about $75 million of consolidated operating cash flows for 2026 for each $0.10 per pound
   (`r3-sens-ocf-copper-step`, added in this stage) change in the average copper price during Q4 2026, at the company's
   stated volumes, costs and other prices. Input: the copper price. Result: ΔOCF ≈ (P − P₀) ÷ step × sensitivity. Shown
   as this project's linear use of the company's approximate figure. No price range is presented as one the company
   confirmed; volumes, costs and the company's other assumptions stay as stated; a volume change from the first
   calculation is never added; the 10-K's older full-year sensitivity is not used.

A closed fold explains why a volume change gives no cash flow figure: the documents give no split of costs into fixed
and variable and no bridge from volume to cash flows, and the 10-K says a significant portion of PTFI's costs are fixed
and unit costs vary with volumes (`k25-ptfi-costs-fixed`). Unit cost is never held constant while volume changes.

Worked example (checked in the tests): from $6.50 to $6.60 at 875 million pounds, price × volume rises by $87.5 million
(`c-q4-copper-revenue-per-10c`); the published sensitivity gives about $75 million. They are different measures; the
page does not put the difference down to taxes, royalties, a cost or timing.

## How it is computed

- `second_order/company_scenarios.py` (company-scenario-0.1) computes with exact decimals on the records as the read
  resolves them, verified on every request. POST /api/companies/fcx/scenario takes `{"mode": "price_volume", "price",
  "volume"}` or `{"mode": "cash_flow", "price"}`, values written as text. Same-origin JSON with the scenario action
  header, administrators only (an /api route). It writes, stores, fetches and calls nothing.
- Input rules: a price above 0 and at most 100 US dollars per pound, to the cent; a volume above 0 and at most 5,000
  million pounds, with at most one decimal. A larger price is refused with a reminder of the unit (a price per tonne or
  in cents is not per pound). With these rules every result is exact in US$ million with at most three decimals, so
  nothing is rounded and the split adds up on screen too.
- A record a calculation uses that is withheld (its document missing or changed) blocks that calculation: 409 with the
  read's fixed reason, and the tab shows why instead of the inputs. The explanations that name those records, or that
  restate a document (each cites its passage), are withheld with them (page.json, as every page text). A 409 while
  the page is open (the document changed after the page was read) makes the page read everything again, so no figure
  or line from the earlier read stays on screen. This holds for a late 409 too, one sent for inputs that have changed
  since: the reply itself is not shown, but the page still reads again.
- When the price change is more than one of the company's steps, the result says how many and that using the figure
  that many times over is this project's arithmetic, not a range the company has confirmed. The worked example
  `c-q4-copper-revenue-per-10c` takes its step from `r3-sens-ocf-copper-step`, so the two cannot drift apart.
- The browser (`frontend/src/companyScenarios.ts`) checks each reply again with BigInt fractions against the verified
  records already on the page: the records and their values, the inputs echoed, each result, and that the split adds up.
  A reply is shown only for the inputs it was computed for: changing an input hides it, and a late reply for earlier
  inputs is never shown (the copper tools' tickets, `copperRequests.ts`).

## Screen

Few inputs and one clear result; formulas, sources and explanations open by choice. Three marks: company assumption
(the F badge), your input, and computed by this project (the C badge). Reset returns to the company's assumptions. The
AI-drafted texts carry the page's stamp. The Overview is unchanged.

## Not in this stage

No valuation, target price, share prices, saved scenarios, database change, new downloads, or change to the copper
calculator's Bagdad figures.
