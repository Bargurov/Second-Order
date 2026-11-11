# FCX stage 1: comparisons and what changed

**AI draft, not reviewed by the project owner.**

- **Figures** are records in `facts.json`, cited by id (P published, C computed). Values are in the company's units:
  USD millions unless stated.
- **"Observation"** lines report figures.
- **"The company's reason"** lines quote the company.
- **"Reading"** lines are the assistant's interpretation. They say what the evidence does not show.

## How to read the periods

| Comparison | Periods | Why it is used |
| --- | --- | --- |
| Quarter | Q3 2026 (1 Jul to 30 Sep 2026) against Q3 2025 | The latest three months, against the same three months a year earlier. The base already includes the start of the mud rush (September 2025), so the incident's full weight is understated here. |
| Nine months | 9M 2026 (1 Jan to 30 Sep 2026) against 9M 2025 | Year to date. 9M 2025 is mostly before the incident, so this comparison shows its fuller effect. |
| Year | FY2025 against FY2024 | From the 10-K. FY2025 holds about a quarter of mud-rush effects (see the annual section). |

Rules kept below:

- **Equal periods only.** A quarter is never compared with nine months or a year, and no change is computed across
  period lengths.
- **Bases stay apart.** Consolidated figures include 100% of PTFI, Cerro Verde and El Abra. Attributable figures are
  FCX common stockholders' share. They sit on separate rows.
- **One-off items stay visible.** They are named, not removed silently. Where this project removes one, the result is
  a computed record that says it is not a company measure.
- **Dates say what kind of date they are.** The 10-Q's date below is its signature date (2026-11-06). Its EDGAR
  filing date is the same day (`sources.md`).

## Quarter: Q3 2026 against Q3 2025

### Observations

- **Headline lines:**

  | Line | Basis | Q3 2026 | Q3 2025 | Change |
  | --- | --- | ---: | ---: | ---: |
  | Revenues | consolidated | 7,546 (`r3-revenues-q3-2026`) | 6,972 | +8.2% (`c-yoy-revenues-q3-2026`) |
  | Operating income | consolidated | 2,353 (`r3-operating-income-q3-2026`) | 1,972 | +19.3% (`c-yoy-operating-income-q3-2026`) |
  | Net income | consolidated | 1,688 (`r3-net-income-q3-2026`) | 1,247 | — |
  | Net income to noncontrolling interests | NCI | 514 (`r3-ni-nci-q3-2026`) | 573 | — |
  | Net income to common stockholders | attributable | 1,174 (`r3-ni-common-is-q3-2026`) | 674 | +74.2% (`c-yoy-ni-common-q3-2026`) |
  | Operating cash flows | consolidated | 1,981 (`r3-ocf-q3-2026`) | 1,689 | +17.3% (`c-yoy-ocf-q3-2026`) |
  | Capital expenditures | consolidated | 1,159 (`r3-capex-q3-2026`) | 1,056 | — |
  | Operating cash flows less capex | consolidated | 822 C (`c-ocf-less-capex-q3-2026`) | 633 C | — |

- **Operating figures (consolidated):**
  - Copper sales fell from 977 to 749 million pounds, −23.3% (`c-yoy-cu-sales-q3-2026`).
  - The realized copper price rose from $4.68 to $6.54 a pound, +39.7% (`c-yoy-cu-price-q3-2026`).
  - Unit net cash costs rose by $0.67 a pound, from $1.40 to $2.07 (`c-chg-cu-unc-q3-2026`).
  - Gold sales fell from 336 to 105 thousand ounces, −68.8% (`c-yoy-au-sales-q3-2026`).
- **Where the copper volume went** (division sales):
  - Indonesia: 360 to 153 million pounds (`r3-id-cu-sales-q3-2026`).
  - South America: 278 to 263 (`r3-sa-cu-sales-q3-2026`).
  - U.S.: 339 to 333 (`r3-us-cu-sales-q3-2026`).
  - Indonesia's share of consolidated copper sales fell from 36.8% to 20.4% (`c-indonesia-share-cu-sales-q3-2026`).
- **Segment operating income:**
  - U.S. copper mines: 396 to 869 (`r3-seg-oi-us-q3-2026`).
  - South America: 493 to 1,014 (`r3-seg-oi-sa-q3-2026`).
  - Indonesia: 1,282 to 616 (`r3-seg-oi-id-q3-2026`).

### What changed

1. **Revenue: the company's own bridge.** The 10-Q (printed page 29) bridges consolidated revenues from 6,972 to
   7,546, line by line. The bridge adds up exactly (`c-rev-bridge-closes-q3-2026`).

   | Line of the company's bridge | Q3 2026 against Q3 2025 |
   | --- | ---: |
   | Copper sales volumes | (1,061) (`q3-rev-bridge-cu-volume-q3-2026`) |
   | Gold sales volumes | (814) (`q3-rev-bridge-au-volume-q3-2026`) |
   | Molybdenum sales volumes | 62 (`q3-rev-bridge-mo-volume-q3-2026`) |
   | Copper realized prices | 1,395 (`q3-rev-bridge-cu-price-q3-2026`) |
   | Gold realized prices | 77 (`q3-rev-bridge-au-price-q3-2026`) |
   | Molybdenum realized prices | 184 (`q3-rev-bridge-mo-price-q3-2026`) |
   | Prior-period provisional pricing adjustments | 41 (`q3-rev-bridge-prior-provisional-q3-2026`) |
   | Higher Atlantic Copper revenues | 479 (`q3-rev-bridge-atlantic-q3-2026`) |
   | Purchased copper | 48 (`q3-rev-bridge-purchased-q3-2026`) |
   | Treatment charges | (4) (`q3-rev-bridge-treatment-q3-2026`) |
   | Lower export duties | 133 (`q3-rev-bridge-export-duties-q3-2026`) |
   | Lower royalties | 49 (`q3-rev-bridge-royalties-q3-2026`) |
   | Other and intercompany eliminations | (15) (`q3-rev-bridge-other-q3-2026`) |

   - **In copper, price outweighed volume:** +1,395 against −1,061.
   - **Across the three metals, volume outweighed price.** The volume lines sum to −1,813
     (`c-rev-bridge-volume-q3-2026`) and the price lines to +1,656 (`c-rev-bridge-price-q3-2026`). Gold makes the
     difference: its volume line is −814 against +77 for its price, as gold sales fell from 336 to 105 thousand
     ounces.
   - **Revenue still rose $574 million, because the other lines sum to +731**
     (`c-rev-bridge-other-lines-q3-2026`), more than the −157 of the metal lines together. The largest is Atlantic Copper (+479), FCX's smelter in Spain.
     - The company's reason for higher production costs starts with "higher costs of copper purchases at Atlantic
       Copper" (`q3-p-cost-drivers`). So that revenue came with purchase costs. The 10-Q gives no figure for the margin.
     - Lower export duties (+133) fit the end of concentrate exports. Duties were charged on concentrate sales until
       the export licence expired in September 2025 (`q3-p-export-duty-expiry`). The bridge itself gives no reason.
   - **The project's own price and volume split** gives +1,393 and −1,067 for copper (`c-cu-price-effect-q3-2026`,
     `c-cu-volume-effect-q3-2026`). It uses rounded per-pound prices. It is kept as a check on the method; the
     company's lines above are the figures to use.
2. **The volume loss is almost all Indonesia.**
   - The company's reason: "primarily reflecting lower operating rates at PTFI during the ramp-up of the Grasberg
     Block Cave underground mine and timing of shipments" (`r3-p-cu-sales-reason`).
   - Production also ran ahead of sales: "production exceeded sales by approximately 11%", from in-process inventory
     at the Indonesian smelters (`r3-p-prod-vs-sales`).
3. **Unit costs rose; the company names lower PTFI volumes and higher input costs.**
   - The company's reason: "the impact of lower copper and gold volumes at PTFI and higher production costs,
     including for energy and other consumables" (`r3-p-unc-reason`). The reports split neither part.
   - Unit net cash costs exclude $244 million of mud-rush idle facility, recovery and restoration costs in the quarter
     (`r3-idle-costs-q3-2026`). Those costs are inside production and delivery costs and operating income.
   - The 10-Q states the excluded costs per pound: $0.33 in Q3 2026 (`q3-idle-pd-per-lb-q3-2026`).
   - *Reading:* comparing unit net cash costs across periods while the ramp-up lasts, read the excluded $0.33 beside
     the $2.07. Adding the two is this project's arithmetic, not a company measure.
4. **More of the profit belongs to FCX's shareholders.**
   - The common stockholders' share of consolidated net income rose from 54.0% to 69.5% (`c-common-share-ni-q3-2026`,
     `c-common-share-ni-q3-2025`).
   - The company's reason for higher net income to common stock: "higher average realized copper and molybdenum
     prices, combined with the impact of lower income taxes and noncontrolling interests from our Indonesia
     operations" (`q3-p-ni-common-reason`).
   - FCX owns 48.76% of PTFI (`r3-ptfi-ownership`), the largest of the three noncontrolling interests
     (`r3-p-nci-sources`).
   - *Reading:* the share moves with the mix of profit. When Indonesia earns less and the wholly owned U.S. mines earn
     more, more of each consolidated dollar is FCX's. The company names this effect alongside price and lower taxes.
     It does not say how much of the rise each one explains.
5. **Operating cash flows rose less than net income to common stockholders.**
   - Operating cash flows rose 17.3%, against +19.3% for operating income and +74.2% for net income to common
     stockholders. The latter is after noncontrolling interests, so it is not on the same basis as consolidated cash
     flow.
   - Cash used for working capital was $0.4 billion in Q3 2026, against $0.2 billion a year earlier
     (`q3-p-wc-quarter`).
   - The company states two related facts. Production ran ahead of sales because of in-process inventory at the
     Indonesian smelters (`r3-p-prod-vs-sales`). It expects 2026 production to exceed sales by about 100 million
     pounds of copper and 70 thousand ounces of gold (`r3-p-wc-deferral`).
   - *Reading:* inventory at the smelters is a likely part of the quarter's working capital use. The reports do not
     split the $0.4 billion, so how much of it is inventory is not stated.

## Nine months: 9M 2026 against 9M 2025

### Observations

- **Headline lines:**

  | Line | Basis | 9M 2026 | 9M 2025 | Change |
  | --- | --- | ---: | ---: | ---: |
  | Revenues | consolidated | 20,809 (`r3-revenues-9m-2026`) | 20,282 | +2.6% (`c-yoy-revenues-9m-2026`) |
  | Operating income | consolidated | 6,493 (`r3-operating-income-9m-2026`) | 5,707 | +13.8% (`c-yoy-operating-income-9m-2026`) |
  | Operating income less the insurance gain | consolidated | 5,794 C (`c-oi-ex-insurance-9m-2026`) | 5,707 | — |
  | Net income to common stockholders | attributable | 3,039 (`r3-ni-common-is-9m-2026`) | 1,798 | +69.0% (`c-yoy-ni-common-9m-2026`) |
  | Operating cash flows | consolidated | 5,524 (`r3-cf-ocf-9m-2026`) | 4,942 | +11.8% (`c-yoy-ocf-9m-2026`) |
  | Operating cash flows less the insurance proceeds | consolidated | 4,825 C (`c-ocf-ex-insurance-9m-2026`) | 4,942 | — |
  | Capital expenditures | consolidated | 3,236 (`r3-capex-9m-2026`) | 3,489 | — |
  | Distributions to noncontrolling interests | NCI | (625) (`r3-cf-dist-nci-9m-2026`) | (1,274) | — |

- **Operating figures:**
  - Copper sales fell 26.1% (`c-yoy-cu-sales-9m-2026`), and the realized price rose 37.4% (`c-yoy-cu-price-9m-2026`).
  - Unit net cash costs rose by $0.48 a pound, to $1.99 (`c-chg-cu-unc-9m-2026`).
- **The company's revenue bridge for the nine months** (10-Q, printed page 29; it adds up exactly,
  `c-rev-bridge-closes-9m-2026`):
  - copper volumes (3,405) and copper prices 3,598 (`q3-rev-bridge-cu-volume-9m-2026`,
    `q3-rev-bridge-cu-price-9m-2026`);
  - all volume lines −5,324 against all price lines +4,483 (`c-rev-bridge-volume-9m-2026`,
    `c-rev-bridge-price-9m-2026`);
  - the other lines +1,368 (`c-rev-bridge-other-lines-9m-2026`), led by Atlantic Copper +905
    (`q3-rev-bridge-atlantic-9m-2026`) and lower export duties +335 (`q3-rev-bridge-export-duties-9m-2026`).
- **Capital expenditure in Indonesia** fell from $1,927 million to $1,435 million (`r3-cf-capex-id-9m-2026`).

### What changed

1. **A one-off gain sits inside both operating income and operating cash flow.**
   - The $699 million PTFI insurance settlement is a negative cost in operating income (`r3-insurance-gain-9m-2026`).
     The cash received is inside operating activities (`r3-cf-insurance-9m-2026`).
   - Without it, nine-month operating income is about level with 9M 2025 (5,794 against 5,707), and operating cash
     flows are lower (4,825 against 4,942). Both are computed and are not company measures.
   - Against that, $934 million of idle facility and restoration costs were charged in 9M 2026, against $171 million
     in 9M 2025 (`r3-idle-costs-9m-2026`).
   - *Reading:* the incident shows up on both sides of the year so far: costs charged to the period, and insurance
     money received. A reader should look at both rather than at the net figure.
2. **Less cash went to minority shareholders.**
   - **Observation:** distributions to noncontrolling interests halved, from $1,274 million to $625 million
     (`r3-cf-dist-nci-9m-2026`). Common dividends were level at $650 million, and buybacks rose to $305 million
     (`r3-cf-buybacks-9m-2026`).
   - **Where the 10-Q says they came from:** "$0.6 billion for the first nine months of 2026 related to Cerro Verde
     and $1.3 billion (including $1.0 billion from PTFI)" in 9M 2025 (`q3-p-nci-distributions`).
     - It names Cerro Verde for 2026 and gives no PTFI figure for 2026.
     - The $0.6 billion is rounded, so a small amount from another subsidiary cannot be ruled out from this sentence.
   - **FCX's own dividends from PTFI are a different flow, and unknown for 2026.**
     - In the consolidated statements, PTFI's payments to its parent are internal to the group. They do not appear as
       distributions to noncontrolling interests.
     - The 10-K disclosed them for 2025: $1.0 billion (`k25-ptfi-dividends-to-fcx-fy2025`).
     - The 10-Q gives no figure for 2026. So whether FCX received a PTFI dividend in 9M 2026 is not known from these
       reports.
   - **The company's general reason:** such distributions "vary based on the operating results and cash requirements of
     our consolidated subsidiaries" (`q3-p-nci-distributions-vary`).
     - Cash held abroad "is generally used to support our foreign operations’ capital expenditures, operating
       expenses, debt repayments, working capital or other cash needs" (`q3-p-cash-international-use`).
     - Cash at international operations was $2.0 billion at 2026-09-30 (`q3-cash-international-2026-09-30`). It is
       not split by subsidiary, and no PTFI cash balance is given.
   - *Reading:* PTFI's ramp-up and smelter restart may be among the "cash requirements" the company's general sentence
     refers to. The 10-Q does not say so for PTFI, and does not say that PTFI kept or built up cash.
3. **Where the nine months' cash went (computed waterfall):**
   - operating cash flows less capital expenditure and distributions to noncontrolling interests: $1,663 million
     (`c-cash-after-nci-9m-2026`);
   - after dividends and buybacks: $708 million (`c-cash-after-returns-9m-2026`).
   - Debt was about level: proceeds of $2,919 million, repayments of $2,904 million.
   - Consolidated cash rose from $3,824 million to $4,335 million (`r3-bs-cash-2025-12-31`, `r3-bs-cash-2026-09-30`).
4. **Net debt fell.** On the company's definition it fell from $5,555 million (computed from the year-end balance
   sheet, `c-net-debt-2025-12-31`) to $5,063 million (`r3-nd-net-debt-2026-09-30`).
   - Excluding PTFI's downstream project debt it fell from $2,320 million (10-K,
     `k25-net-debt-ex-ptfi-downstream-2025-12-31`) to $1,826 million (`r3-nd-net-debt-ex-2026-09-30`). That is below
     the company's $3.0 to $4.0 billion target range (`r3-net-debt-target`).

## Year: FY2025 against FY2024

All figures in this section are from the 2025 10-K.

### Observations

- **Headline lines:**

  | Line | Basis | FY2025 | FY2024 | Change |
  | --- | --- | ---: | ---: | ---: |
  | Revenues | consolidated | 25,915 (`k25-revenues-fy2025`) | 25,455 | +1.8% (`c-yoy-revenues-fy2025`) |
  | Operating income | consolidated | 6,518 (`k25-operating-income-fy2025`) | 6,864 | −5.0% (`c-yoy-operating-income-fy2025`) |
  | Net income | consolidated | 4,152 (`k25-net-income-consolidated-fy2025`) | 4,399 | −5.6% (`c-yoy-net-income-consolidated-fy2025`) |
  | Net income to noncontrolling interests | NCI | (1,948) (`k25-net-income-nci-fy2025`) | (2,510) | — |
  | Net income to common stockholders | attributable | 2,204 (`k25-net-income-common-fy2025`) | 1,889 | +16.7% (`c-yoy-net-income-common-fy2025`) |
  | Operating cash flows | consolidated | 5,610 (`k25-operating-cash-flow-fy2025`) | 7,160 | −21.6% (`c-yoy-operating-cash-flow-fy2025`) |
  | Capital expenditures | consolidated | 4,494 (`k25-capex-total-fy2025`) | 4,808 | −6.5% (`c-yoy-capex-total-fy2025`) |
  | Operating cash flows less capex | consolidated | 1,116 C (`c-ocf-less-capex-fy2025`) | 2,352 C (`c-ocf-less-capex-fy2024`) | — |
  | Distributions to noncontrolling interests | NCI | (1,274) (`k25-distributions-paid-nci-fy2025`) | (1,833) | — |
  | Dividends on common stock | attributable | (865) (`k25-dividends-paid-common-fy2025`) | (865) | — |

- **Operating figures (consolidated):**
  - Copper sales fell 12.1% to 3,574 million lb (`c-yoy-copper-sales-fy2025`), and production fell 19.7%
    (`c-yoy-copper-production-fy2025`).
  - The realized copper price rose 12.8% to $4.75 (`c-yoy-copper-realized-price-fy2025`).
  - Unit net cash costs rose by $0.09 to $1.65 (`c-chg-unit-net-cash-costs-fy2025`). They exclude $0.17 a pound of
    mud-rush costs (`k25-mud-rush-cost-per-lb-excluded-fy2025`).
  - Gold sales fell 42.0% (`c-yoy-gold-sales-fy2025`).
- **Indonesia:** copper sales fell from 1,632 to 1,205 million lb (`k25-ptfi-copper-sales-fy2025`). Its share of
  consolidated copper sales fell from 40.1% to 33.7% (`c-indonesia-share-cu-sales-fy2025`,
  `c-indonesia-share-cu-sales-fy2024`).
- **Mud-rush costs in 2025:** $743 million in all (`k25-mud-rush-idle-and-recovery-costs-total-fy2025`). That is $625
  million in production and delivery (`k25-mud-rush-idle-and-recovery-costs-pd-fy2025`) and $118 million in DD&A
  (`k25-mud-rush-idle-costs-dda-fy2025`).
- **Working capital and other uses:** $1.3 billion in 2025, against $29 million in 2024
  (`k25-working-capital-and-other-uses-fy2025`, `k25-working-capital-and-other-uses-fy2024`).

### What changed

1. **Revenue: the company's bridge** (10-K, printed page 91; it adds up exactly, `c-rev-bridge-closes-fy2025`).
   - **In copper, price and volume nearly cancelled:** prices +1,930, volumes −2,073 (`k25-rev-bridge-cu-price-fy2025`,
     `k25-rev-bridge-cu-volume-fy2025`).
   - **Across the three metals, volume outweighed price:** −3,917 against +3,072 (`c-rev-bridge-volume-fy2025`,
     `c-rev-bridge-price-fy2025`). Gold volumes alone were −1,954 (`k25-rev-bridge-au-volume-fy2025`).
   - **The other lines added +1,305** (`c-rev-bridge-other-lines-fy2025`). The largest is "Other, including
     intercompany eliminations" at +812 (`k25-rev-bridge-other-fy2025`), which the 10-K does not explain further. Then
     lower treatment charges +333 and lower export duties and royalties +208.
   - The mud rush hit only the last four months. The company says "The incident impacted our results for the second
     half of 2025" (`k25-mud-rush-2026-impact`).
2. **Profit fell for the group but rose for FCX's shareholders.**
   - Net income to noncontrolling interests fell from $2,510 million to $1,948 million.
   - Indonesia's part of it fell from $2,022 million to $1,325 million (`k25-nci-net-income-indonesia-fy2025`).
   - The common stockholders' share of consolidated net income rose from 42.9% to 53.1% (`c-common-share-ni-fy2024`,
     `c-common-share-ni-fy2025`).
   - Indonesia carries the largest noncontrolling interest, so its lower profit moved the split, as in Q3 2026.
3. **Operating cash flows fell more than net income.** Operating cash flows fell 21.6%, and operating cash flows less
   capital expenditure halved, to $1,116 million.
   - The company's reason for lower operating cash flows: "lower copper and gold sales volumes, primarily resulting
     from the September 2025 mud rush incident at PTFI, partly offset by higher copper and gold prices"
     (`k25-p-ocf-reason-fy2025`).
   - The company's reason for the $1.3 billion of working capital and other uses: "an increase in accounts receivable
     associated with higher prices and the timing of sales and associated collections, as well as higher tax payments
     in Indonesia" (`k25-p-wc-reason-fy2025`). That was "partly offset by increased accruals from the timing of
     purchases, and reserves associated with asbestos and talc claims" (`k25-p-wc-offset-fy2025`).
   - The 10-K gives no amount for each reason.

### The ramp path of copper sales (consolidated, million lb)

| Period | Copper sales | Record |
| --- | ---: | --- |
| Q3 2025 | 977 | `r3-cu-sales-q3-2025` |
| Q4 2025 (implied: FY2025 less 9M 2025) | 709 C | `c-cu-sales-q4-2025` (assumption `a-q4-2025-same-basis`) |
| H1 2026 (implied: 9M 2026 less Q3 2026) | 1,367 C (about 684 a quarter) | `c-cu-sales-h1-2026` |
| Q3 2026 | 749 | `r3-cu-sales-q3-2026` |
| Q4 2026 (outlook, 2026-10-27) | 875 | `r3-out-cu-sales-q4-2026` |

- **Observation:** Q3 2026 sales (749) were above Q4 2025 (709, implied) and above the H1 2026 average (about 684).
- **What cannot be told:** H1 2026 is only a total. Q1 and Q2 were not collected, so whether Q3 2026 is the first
  quarter above them is not known. One of them may have been as high.

## How the 2026 outlook changed between February and October

These are outlooks, not results. Each rests on its own price assumptions:

- **10-K (2026-02-13):** $5.00 a pound copper, $4,000 an ounce gold and $20.00 a pound molybdenum for 2026
  (`k25-outlook-price-assumption-copper-fy2026`).
- **Q3 2026 reports (the release of 2026-10-27 and the 10-Q, signature date 2026-11-06):** the nine months' actual
  prices, plus $6.50, $4,000 and $32.00 for Q4 2026.

So a change in a cash figure mixes price and operations. Read the volume and cost lines for the operational change.

| Line | 10-K outlook | Q3 2026 outlook | Records |
| --- | ---: | ---: | --- |
| Copper sales, consolidated | 3,380 million lb | about 3.0 billion lb | `k25-outlook-copper-sales-total-fy2026`, `q3-outlook-cu-sales-total-fy2026` |
| of which Indonesia | 900 million lb | about 0.7 billion lb | `k25-outlook-copper-sales-indonesia-fy2026`, `q3-outlook-cu-sales-indonesia-fy2026` |
| Gold sales | 800 thousand oz | 649 thousand oz | `k25-outlook-gold-sales-fy2026`, `q3-outlook-au-sales-fy2026` |
| Unit net cash costs (non-GAAP) | $1.75 a pound | $1.90 a pound | `k25-outlook-unit-net-cash-costs-fy2026`, `q3-outlook-uncc-consolidated-fy2026` |
| PTFI idle facility costs | $0.9 billion | $1.2 billion | `k25-idle-facility-costs-outlook-fy2026`, `q3-outlook-idle-costs-fy2026` |
| Operating cash flows | about $8 billion, including $1 billion of working capital and other sources | about $8.5 billion, net of $0.6 billion of working capital and other uses | `k25-outlook-operating-cash-flows-fy2026`, `q3-outlook-ocf-fy2026` |
| Capital expenditures | $4.3 billion | $4.4 billion | `k25-outlook-capex-total-fy2026`, `q3-outlook-capex-total-fy2026` |
| Net income to noncontrolling interests | $2.4 billion | $2.3 billion | `k25-outlook-net-income-nci-fy2026`, `q3-outlook-nci-fy2026` |

- **Observation:** against February, the October outlook has lower volumes (especially Indonesia's), higher unit
  costs and idle costs, and working capital turned from an expected source of $1 billion into a use of $0.6 billion.
  The operating cash flow outlook is still higher.
- **What is not stated:** the company does not bridge the two outlooks.
- *Reading:* the price assumptions are the largest difference between the two outlooks (a $5.00 year in February; the
  nine months' actual prices plus $6.50 in October). That fits a higher cash outlook despite weaker operations, but it
  is not measured. The company's sensitivities cannot size it either: each is for a different period of price change
  (`mechanisms.md`, section 9).
- The October outlook was published before the board approved the Bagdad expansion (2026-11-04). The company says its
  capital expenditure outlook will be updated for it (`nr-p-discretionary`).

## The Bagdad expansion: how the company's statements changed

**The decision (stated as fact by the company):** "its Board of Directors approved a $4.5 billion expansion and
modernization program for its wholly owned Bagdad copper and molybdenum operation in northwest Arizona"
(`nr-p-board-approval`, release of 2026-11-04). The 10-Q (signature date 2026-11-06) says the same, dated "November
2026" (`q3-p-bagdad-approval`).

Everything else below is a company estimate or plan, as stated on each date.

| What the company stated | 10-K (2026-02-13) | Results release (2026-10-27) | Bagdad release (2026-11-04) |
| --- | --- | --- | --- |
| Status | studies being updated "in advance of a potential investment decision during 2026" (`k25-p-bagdad-decision-2026`) | "expects to reach an investment decision … in fourth-quarter 2026" (`r3-p-bagdad-decision`) | approved by the board (`nr-p-board-approval`) |
| Capital cost | about $3.5 billion, "continue to be reviewed" (`k25-bagdad-capex-estimate`) | about $4.5 billion, "current estimates, which remain under review" (`r3-bagdad-capex-estimate`) | about $4.5 billion, expected (`nr-bagdad-capex-estimate`); estimates "could" change with inflation (`nr-p-cost-risk`) |
| Added copper a year | 200 to 250 million lb (`k25-bagdad-cu-increment-low`, `k25-bagdad-cu-increment-high`) | 200 to 250 million lb (`r3-bagdad-cu-increment-low`, `r3-bagdad-cu-increment-high`) | about 225 million lb, total over 400 (`nr-bagdad-cu-increment`, `nr-bagdad-cu-total`) |
| Added molybdenum a year | not stated in the passage read | 10 to 12 million lb (`r3-bagdad-mo-increment-low`, `r3-bagdad-mo-increment-high`) | about 12 million lb, total over 20 (`nr-bagdad-mo-increment`, `nr-bagdad-mo-total`) |
| Copper price named | "incentive copper price of approximately $4.00" (`k25-bagdad-incentive-price`) | "incentive copper price of approximately $4.00" (`r3-bagdad-incentive-price`) | "break-even economics supported at a copper price of approximately $4.00" with $20 molybdenum (`nr-bagdad-breakeven-cu`, `nr-bagdad-breakeven-mo`) |
| Time | "three to four years to complete" (`k25-bagdad-incentive-price`) | "three to four years to complete" (`r3-p-bagdad-price`) | construction about 3.5 years, "initial production targeted in mid-2030" (`nr-p-schedule`) |

- **Computed:** the capital estimate rose 28.6% between February and November (`c-bagdad-capex-estimate-change`).
  The 10-K's wording and the later wording differ, and no report says whether the scope changed.
- **Terms kept as written.** "Incentive price" (February, October) and "break-even economics" (November) are kept in
  each document's words. They are not treated as the same measure.
- **The 10-Q matches the November release** on capital cost, added copper and added molybdenum (cross-checked pairs in
  `facts.json`).
- **Not updated elsewhere.** The copper calculator still carries the 10-K figures for Bagdad ($3.5 billion; 200 to 250
  million lb). Neither the calculator nor the copper thesis was changed in this round (`gaps.md`, section E).

## The release and the 10-Q show different 2025 operating cash flows

- **Agreement:** 89 pairs of records that state the same figure in two documents agree (`cross_checks` in
  `facts.json`).
- **One difference:** the 10-Q (signature date 2026-11-06) shows 2025 operating cash flows $25 million lower than the
  release of 2026-10-27.
  - Q3 2025: 1,664 against 1,689.
  - 9M 2025: 4,917 against 4,942 (`c-ocf-difference-q3-2025`, `c-ocf-difference-9m-2025`).
  - In the 9M 2025 column, two lines differ by the same $25 million:
    - accounts receivable in operating activities: (433) in the 10-Q, (408) in the release;
    - "Other, net" in investing activities: 47 in the 10-Q, 22 in the release.
  - Neither document mentions or explains the difference. Neither calls it a restatement or a correction, so it is
    described here only as a difference between the amounts shown.
- **On the 10-Q's comparatives:**
  - Operating cash flows rose 19.1% in the quarter and 12.3% in the nine months (`c-yoy-ocf-q3-2026-10q`,
    `c-yoy-ocf-9m-2026-10q`), against 17.3% and 11.8% on the release's.
  - Operating cash flows less capex were 608 (Q3 2025) and 1,428 (9M 2025) (`c-ocf-less-capex-q3-2025-10q`,
    `c-ocf-less-capex-9m-2025-10q`).
- **Which to use:** the tables above use the release's figures, so that every quarter figure comes from one document.
  Both figures are kept. The 10-Q is the later document by its signature date.
