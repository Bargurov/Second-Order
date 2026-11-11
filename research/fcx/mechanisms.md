# FCX stage 1: how copper reaches cash flow (mechanism map)

**AI draft, not reviewed by the project owner.**

The map follows each driver from the copper market to FCX's operating cash flow, and then to the cash left for FCX's
own shareholders. Each link carries one of the kinds used by the copper exposure map (`docs/copper-exposure-map.md`):

- **Stated:** a retained report states the link, often with a figure (record or passage cited).
- **Conditional:** general economics that should hold, but the reports do not measure it for FCX.
- **Not measured:** the reports give no figure, and this package does not estimate one.

```text
copper price (LME / COMEX)
   │ stated: realized price follows monthly average settlement prices; provisional pricing 1–4 months
   ▼
realized price × sales volume ──────────── revenue (consolidated)
   │                                         │ stated: by-product credits (gold, molybdenum) lower unit costs
   │ stated: volumes = production ± inventory │ stated: idle facility costs during the Grasberg ramp-up
   ▼                                         ▼
site cash costs, royalties, export duties, profit sharing, taxes (several rise with price: conditional)
   ▼
operating cash flows (consolidated)  ◄── working capital (stated: smelter inventories hold cash back in 2026)
   │
   ├── capital expenditures (stated: 2026 outlook; Bagdad approved 2026-11-04; other projects with incentive prices)
   ├── distributions to noncontrolling interests (stated: PTFI, Cerro Verde, El Abra)
   ▼
cash for FCX's own uses ── financial policy (stated: up to 50% of available cash flows to shareholders, net debt target)
```

## 1. Price → realized price → revenue

- **Stated: which price.**
  - Copper from South America and Indonesia is sold on LME monthly averages. U.S. copper is sold on COMEX monthly
    averages: "copper sales from U.S. copper mines that are generally based on prevailing Commodity Exchange Inc.
    (COMEX) monthly average settlement copper prices" (`r3-p-realized-basis`).
  - In Q3 2026 the LME average was $6.40 a pound (`r3-lme-avg-q3-2026`) and COMEX $6.48 (`r3-comex-avg-q3-2026`).
    FCX realized $6.54 (`r3-cu-price-q3-2026`).
- **Stated: provisional pricing.** It carries a price move across quarters.
  - Concentrate and some cathode contracts "provide final copper pricing in a specified future month (generally one to
    four months from the shipment date)" (`r3-p-provisional`).
  - The open position is marked to forward prices each period (`r3-p-embedded`).
  - At 30 September 2026, 239 million pounds were open at $6.55 a pound. That is 134 million pounds net of
    intercompany sales and noncontrolling interests (`r3-provisional-lbs`).
  - The company states this sensitivity in two measures: about $12 million of 2026 revenue, and $4 million of net
    income attributable to common stock, per $0.05 a pound (`r3-provisional-sens`). Both are as published, and apply
    only to that open position.
- **Stated: how the mix is sold.** In 9M 2026 mined copper was sold 37% as cathode, 35% as rod and 28% as concentrate
  (`r3-sales-mix-cathode-9m-2026`).
- **Stated, with figures: the company's revenue bridge.** The 10-Q splits the change in consolidated revenues into
  volume, price and other lines (printed page 29; the table is in `comparison.md`).
  - Q3 2026 against Q3 2025: copper prices +$1,395 million (`q3-rev-bridge-cu-price-q3-2026`), copper volumes
    −$1,061 million (`q3-rev-bridge-cu-volume-q3-2026`).
  - All three metals: price lines +$1,656 million, volume lines −$1,813 million (`c-rev-bridge-price-q3-2026`,
    `c-rev-bridge-volume-q3-2026`).
  - The other lines that move revenue are named in the bridge: gold volumes, Atlantic Copper's revenues, export
    duties and royalties, among others. Only the company's "Other and intercompany eliminations" line is not explained
    further.

## 2. Volume → revenue and unit costs

- **Stated: Grasberg is the swing.**
  - At normal rates PTFI's underground mines produce about 1.7 billion pounds of copper and 1.3 million ounces of gold
    a year (`r3-ptfi-normal-rates`).
  - In Q3 2026 its mills ran at 141 thousand tonnes a day, 67% of capacity (`r3-mill-throughput-q3-2026`).
  - PTFI expects "80% of capacity in mid-2027" and to "approach full capacity by year-end 2027" (`r3-p-ramp-up`).
- **Stated: production and sales differ.** Inventory sits at the Indonesian smelters: production exceeded sales by
  about 11% in Q3 2026 (`r3-p-prod-vs-sales`). The 2026 deferral is about 100 million pounds of copper and 70 thousand
  ounces of gold (`r3-p-wc-deferral`).
- **Stated: lower volume raises unit costs.** "the impact of lower copper and gold volumes at PTFI" is the company's
  first reason for higher unit net cash costs (`r3-p-unc-reason`).
  - During the ramp-up, "a portion of PTFI's production and delivery costs will be recognized as idle facility costs,
    which are non-inventoriable" (`r3-p-idle-costs`).
  - These idle costs were $244 million in Q3 2026 (`r3-idle-costs-q3-2026`), and are excluded from unit net cash
    costs.
- **Stated for PTFI, without a figure:** "A significant portion of PTFI's costs are fixed and unit costs vary
  depending on volumes and other factors" (`k25-ptfi-costs-fixed`).
- **Conditional elsewhere:** the same operating leverage is plausible at the other mines, but not stated.
  - Not measured: the reports give no split of fixed and variable cost.

## 3. By-products → unit net cash costs

- **Stated: by-product credits.** Under FCX's by-product method, "gold, molybdenum and other metal revenues at copper
  mines are reflected as credits against site production and delivery costs" (`r3-p-byproduct-method`).
  - Indonesia's gold makes its unit figure a credit: −$0.84 a pound in Q3 2026 (`r3-id-unc-q3-2026`), with by-product
    credits of $3.52 a pound (`r3-id-byproduct-q3-2026`).
- **Stated, with figures, in the company's measure (unit net cash costs for 2026):** "$0.01 per pound of copper for
  each $100 per ounce change in the average price of gold during fourth-quarter 2026" (`r3-p-unc-sens`). The release
  states the same for each $2 a pound of molybdenum.
- **Stated: timing matters.** About 60 thousand ounces of gold slid from Q3 into Q4 2026 (`r3-p-gold-deferral`). The
  company says unit costs were above its July estimate "primarily reflecting lower by-product credits as a result of
  the deferral of gold sales" (`r3-p-unc-vs-estimate`).

## 4. Input costs

- **Stated, without figures:**
  - higher energy and consumables costs (`r3-p-unc-reason`);
  - employee profit sharing at Cerro Verde (`r3-p-sa-unc-reason`);
  - weather at the U.S. mines (`r3-p-us-weather`).
- **Not measured:** how much of the cost base is energy, or how cost moves with energy prices.

## 5. Royalties, duties, profit sharing and taxes

These absorb part of a price rise before it reaches cash.

- **Stated: per-pound items in Indonesia.**
  - Royalties on metals were $0.36 a pound in Q3 2026, against $0.29 (`r3-id-royalty-q3-2026`,
    `r3-id-royalty-q3-2025`).
  - Export duties were $0.01, against $0.38 (`r3-id-export-duties-q3-2026`, `r3-id-export-duties-q3-2025`).
  - **Stated: why export duties fell.** Before its export licence expired on 2025-09-16, PTFI paid export duties "on
    copper concentrate sales at a rate of 7.5%" (`q3-p-export-duty-expiry`). With concentrate no longer exported,
    that duty fell away.
    - The release does not say what the remaining $0.01 a pound is.
    - A separate 10% duty on refined gold exports is unresolved (`q3-p-gold-export-duty`).
- **Stated: the Indonesian fiscal terms.** "a 25% corporate income tax rate, a 10% profits tax on net income, and
  royalty rates of 4% for copper, 3.75% for gold and 3.25% for silver" (`k25-iupk-fiscal-terms`).
  - PTFI's royalties were $345 million in 2025 and its export duties $337 million (`k25-ptfi-royalties-fy2025`,
    `k25-ptfi-export-duties-fy2025`).
  - Concentrate export duties ended with the export licence on 2025-09-16 (`k25-export-licence-expired`).
- **Stated: tax rates.**
  - The expected consolidated effective tax rate for 2026 is about 30% (`r3-out-etr-fy2026`). That includes Peru 40%,
    Indonesia 36% and the U.S. 10%.
  - The U.S. figure "primarily relates to the U.S. Corporate Alternative Minimum Tax (CAMT) provisions" (`r3-p-camt`).
- **Conditional: price-linked costs.** Royalties, profit sharing and income taxes rise with price, so less than the
  full gross revenue change reaches operating cash flow.
  - Computed: Q4 2026 copper sales outlook × $0.10 a pound = $87.5 million of gross sales
    (`c-q4-copper-revenue-per-10c`, assumption `a-q4-price-arithmetic`). The company's own figure for that price change
    is $75 million of operating cash flows (section 9).
  - Not measured: the company does not give the bridge.
  - Candidate reasons, none confirmed: price-linked royalties, profit sharing and taxes, and the timing of when a
    fourth-quarter price change is settled and collected relative to the year-end.
  - Do not read the gap as a tax rate.

## 6. Working capital

- **Stated: working capital held cash back.**
  - $0.4 billion of working capital and other uses in Q3 2026, and $0.8 billion in 9M 2026 (note on `r3-ocf-q3-2026`).
  - Inventories used $601 million in 9M 2026 (`r3-cf-inventories-9m-2026`).
  - The 2026 outlook is net of $0.6 billion of working capital and other uses (`r3-out-ocf-fy2026`).
- **Conditional: the cash comes back.** When the smelter inventory is sold, it should return cash. Its timing depends
  on the smelter ramp-up and on gold export permissions (`r3-p-gold-export`).

## 7. Capital expenditure → cash after investment, and future volume

- **Stated: the 2026 outlook.** About $4.4 billion, including $3.0 billion for major mining projects
  (`r3-out-capex-fy2026`, `r3-out-capex-major-fy2026`). That splits into $1.4 billion planned and $1.6 billion
  discretionary growth.
- **Stated: Bagdad is now a decision, not an option.** The parts are kept apart.
  - **The decision (a fact, as the company states it):** on 2026-11-04 the company announced that "its Board of
    Directors approved a $4.5 billion expansion and modernization program" for Bagdad (`nr-p-board-approval`). The 10-Q
    repeats it (`q3-p-bagdad-approval`).
  - **What is already happening (stated):**
    - "engineering, procurement planning and early works" (`nr-p-early-works`);
    - the 2026 discretionary capex outlook already includes "early works associated with the expansion project"
      (`q3-p-bagdad-early-works`).
  - **The company's estimates and plans (not results):**
    - capital cost about $4.5 billion (`nr-bagdad-capex-estimate`); the company says inflation and cost escalation
      "could affect these estimates" (`nr-p-cost-risk`), and "aims to complete the project within current cost
      estimates and timelines" (`nr-p-aim`);
    - funding: about 20% in 2027, 30–35% in 2028, the balance in 2029–2030 (`nr-p-funding-schedule`);
    - spending to be classified as discretionary under the financial policy, and added to an updated capex outlook
      (`nr-p-discretionary`);
    - construction about 3.5 years, "initial production targeted in mid-2030" (`nr-p-schedule`);
    - long-term production of over 400 million pounds of copper a year, of which about 225 million incremental
      (`nr-bagdad-cu-total`, `nr-bagdad-cu-increment`). Molybdenum: over 20 million pounds, about 12 million
      incremental (`nr-bagdad-mo-total`, `nr-bagdad-mo-increment`);
    - about 20% lower long-term unit net cash costs (`nr-bagdad-uncc-reduction`), with no base level or year given;
    - break-even economics supported at about $4.00 a pound copper and $20 a pound molybdenum
      (`nr-bagdad-breakeven-cu`, `nr-bagdad-breakeven-mo`).
  - **History (stated facts):** operating since 1945, reserve life over 80 years (`nr-p-history`). The first major U.S.
    mine with a fully autonomous haul fleet, from 2025 (`nr-p-autonomous`). 149 million pounds of copper produced in
    2025 (`k25-bagdad-cu-production-fy2025`).
  - **Computed from the company's estimates (not company figures):**
    - implied funding of about $0.9 billion in 2027 (`c-bagdad-funding-2027`), $1.35–1.575 billion in 2028
      (`c-bagdad-funding-2028-low`, `c-bagdad-funding-2028-high`), and $2.025–2.25 billion across 2029–2030
      (`c-bagdad-funding-2029-2030-low`, `c-bagdad-funding-2029-2030-high`). The amounts move if the estimate moves
      (`a-bagdad-funding-arithmetic`);
    - as a size reference, the added copper equals 6.3% of 2025 consolidated copper sales and 9.1% of FCX's net
      copper sales (`c-bagdad-cu-increment-share-fy2025`, `c-bagdad-cu-increment-share-net-fy2025`). Bagdad is wholly
      owned, so all of it would be FCX's. This is not a volume forecast (`a-bagdad-scale-reference`);
    - the capital estimate is 28.6% above the 10-K's $3.5 billion (`c-bagdad-capex-estimate-change`). Whether the scope
      is the same is not stated.
- **Stated: other growth options, each with its own condition.**
  - El Abra: about $7.5 billion, on estimates prepared in 2024 (`r3-p-el-abra`).
  - Kucing Liar: about $4 billion more through 2033 (`r3-p-kucing-liar`).
- **Conditional: today's capex is tomorrow's volume.** Spending now buys future volume, which is the mechanism of
  section 2 at a later date. Bagdad now has a stated start date and annual rate, but no year-by-year ramp. Not
  measured: the reports give no volume path for the projects together that could be added up.

## 8. Noncontrolling interests → cash for FCX's shareholders

- **Stated: who shares the profit.** Consolidated figures include partners' shares. Noncontrolling interests are
  "associated with PTFI, Cerro Verde and El Abra" (`r3-p-nci-sources`).
  - FCX owns 48.76% of PTFI (`r3-ptfi-ownership`) and 55.66% of Cerro Verde (`r3-cerro-verde-ownership`).
  - Morenci is proportionately consolidated at 72%, so it carries no noncontrolling interest
    (`r3-morenci-interest`).
- **Stated: what partners receive.**
  - Distributions to noncontrolling interests were $625 million in 9M 2026 (`r3-cf-dist-nci-9m-2026`).
  - Net income attributable to them is expected at about $2.3 billion for 2026 (`r3-out-nci-ni-fy2026`).
  - Their share of consolidated cash was $0.9 billion (`r3-cash-nci-share`).
- **Computed, with the company's reason: the attributable share rose as Indonesia's weight fell.** The common
  stockholders' share of consolidated net income rose from 54.0% to 69.5% (`c-common-share-ni-q3-2025`,
  `c-common-share-ni-q3-2026`). FCX's net copper sales are 73.7% of consolidated in Q3 2026, against 68.2%
  (`c-net-share-cu-sales-q3-2026`, `c-net-share-cu-sales-q3-2025`).
  - The company names "lower income taxes and noncontrolling interests from our Indonesia operations", alongside
    higher prices (`q3-p-ni-common-reason`). It does not say how much each explains.
- **Stated: rules on how cash inside PTFI moves.**
  - 100% of PTFI's export proceeds must be deposited in Indonesian banks for 12 months (`k25-export-proceeds-rule`),
    though they may fund business needs, dividends and taxes (`q3-p-export-proceeds-100pct`).
  - "Dividends from subsidiaries that are not wholly owned are shared with other equity owners"
    (`k25-holding-company-dividends-shared`).
  - For 9M 2026 the 10-Q attributes the distributions to noncontrolling interests to Cerro Verde, and gives no PTFI
    figure (`q3-p-nci-distributions`).
  - **A different flow:** PTFI's dividends to FCX itself are internal to the group, so they are not in the
    consolidated cash flow statement. The 10-K disclosed $1.0 billion for 2025 (`k25-ptfi-dividends-to-fcx-fy2025`).
    The 10-Q gives no figure for 2026, so FCX's PTFI dividend in 2026 is unknown here.
- **Stated: the long run.** Under the 2026 MOU, FCX "would maintain its current ownership interest in PTFI of 48.76%
  through 2041 and hold approximately 37% beginning in 2042" (`r3-p-mou`).
  - This matters for valuation (next stage). It is not used here.

## 9. Published sensitivities, exactly as defined

| Record | Measure (the company's) | Per | Period of the price change | Effect on | Conditions |
| --- | --- | --- | --- | --- | --- |
| `r3-sens-ocf-copper` | operating cash flows | $0.10/lb change in the average copper price | Q4 2026 only | the year 2026 | current sales volume and cost estimates; $6.50/lb copper, $4,000/oz gold, $32.00/lb molybdenum in Q4 2026 (`r3-p-sens-conditions`) |
| `r3-sens-ocf-gold` | operating cash flows | $100/oz change in the average gold price | Q4 2026 only | the year 2026 | as above |
| `r3-sens-ocf-moly` | operating cash flows | $2/lb change in the average molybdenum price | Q4 2026 only | the year 2026 | as above |
| `r3-provisional-sens` | revenues; and net income attributable to common stock | $0.05/lb change from the quarter-end provisional price | settlement of sales open at 2026-09-30 | 2026 | the 239 million pounds open at $6.55/lb |
| `r3-p-unc-sens` | unit net cash costs | $100/oz change in gold (and $2/lb molybdenum) | Q4 2026 only | the year 2026 | current sales volume and cost estimates |

The 10-K (2026-02-13) published its own 2026 sensitivities under different conditions:

| Record | Measure (the company's) | Per | Period of the price change | Effect on | Conditions |
| --- | --- | --- | --- | --- | --- |
| `k25-sensitivity-ocf-copper-fy2026` | operating cash flows | $0.10/lb change in the average copper price | the year 2026 (the whole year, as of February) | the year 2026 | $5.00/lb copper, $4,000/oz gold, $20.00/lb molybdenum for 2026; about $8 billion of operating cash flows including $1 billion of working capital and other sources (`k25-ocf-outlook-conditions`, `k25-ocf-sensitivity-wording`) |
| `k25-sensitivity-ocf-gold-fy2026` | operating cash flows | $100/oz change in the average gold price | the year 2026 | the year 2026 | as above (`k25-ocf-sensitivity-wording-2`) |
| `k25-sensitivity-ocf-moly-fy2026` | operating cash flows | $2/lb change in the average molybdenum price | the year 2026 | the year 2026 | as above |
| `k25-sensitivity-net-income-nci-copper-fy2026` | net income attributable to noncontrolling interests | $0.25/lb change in the copper price | the year 2026 | the year 2026 | the 10-K's 2026 assumptions (printed page 94) |
| `k25-sensitivity-unit-cost-gold-fy2026` | unit net cash costs | $100/oz change in gold (and $2/lb molybdenum, `k25-sensitivity-unit-cost-moly-fy2026`) | the year 2026 | the year 2026 | $4,000/oz gold and $20.00/lb molybdenum (`k25-uncc-outlook-assumptions`) |

The copper figures are $330 million (February, a change across all of 2026) and $75 million (October, a change in
Q4 2026 only). They are not two estimates of one quantity:

- the period over which the price changes differs;
- the price level differs ($5.00 against $6.50);
- the volume outlook differs.

The company does not bridge the two, and neither figure is converted into the other here.

The NCI sensitivity is the only published one stated in an attributable-to-others measure. It is net income, not
cash flow, and stays in that measure.

How to use them, and how not to:

- **Use them as published.** Each is a statement about one measure, one period of price change and one set of
  assumptions. The copper figure is $75 million of 2026 operating cash flows per $0.10 a pound, for a price change in
  the fourth quarter only.
- **No conversions.** It is not a sensitivity of earnings, EBITDA or the share price. It is not a full-year figure, and
  it cannot be scaled to another price level or year.
- **No merging.** The 10-K's sensitivity and the release's describe different periods and assumptions. They sit side by
  side and are not merged or reconciled into one number.
