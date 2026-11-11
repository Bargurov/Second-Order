# FCX stage 1: missing information and questions to follow

**AI draft, not reviewed by the project owner.** Four kinds of item:

- what the four retained documents do not give;
- what this stage did not collect;
- questions worth following;
- what was deliberately left unchanged elsewhere in the project.

None of them is answered by guessing here.

## A. Source and provenance gaps

1. **The SEC copies of the 10-Q and of the two news releases: closed on 2026-11-11.**
   - The package reads the SEC EDGAR copies: the 10-Q (accession 0000831259-26-000051) and the two releases, each
     exhibit 99.1 to a Form 8-K (0000831259-26-000045, furnished under Items 2.02 and 7.01, and 0000831259-26-000048,
     attached under Item 8.01). See `sources.md`.
   - Every record and passage resting on them was matched against the SEC text (`sec-match.md`): 749 exact, 6 that
     differed only in spacing, none relaid, none not found, no definition changed.
   - The EDGAR filing dates (2026-11-06, 2026-10-27 and 2026-11-04) equal the dates already used.
   - The earlier copies of the three documents are kept privately and no longer read. They are described in
     `sources-private.md` (private; not in the public repository).
2. **The 10-K's EDGAR filing date** was not read from its filing index. The date used is the signature date
   (2026-02-13), which matches the EDGAR file's Last-Modified header. The EDGAR submissions record retained on
   2026-11-11 (fcx-sec-locate-02) gives the same day as the filing date of accession 0000831259-26-000012; the 10-K's
   entry in `sources.json` was not changed.
3. **The Bagdad release is read from its exhibit's text.** The SEC exhibit shows its three pages as images, which were
   retained by `fcx-sec-images-02` and compared visually with the text (no difference), and carries the release's text
   in the file. The quotes match that text, word for word as on the earlier copy (`sec-match.md`).

## B. Missing from these documents (or not given at the level needed)

These items come from the extraction. Each was found while recording figures, not by searching for problems.

1. **The revenue bridge exists, but it stops at revenue.**
   - **A correction:** the first version of this package said no bridge was given. That was wrong. The 10-Q bridges
     consolidated revenues for the quarter and the nine months (printed page 29), and the 10-K for the year (printed
     page 91). The records are `q3-rev-bridge-*` and `k25-rev-bridge-*`, and each bridge adds up exactly
     (`c-rev-bridge-closes-q3-2026`, `c-rev-bridge-closes-9m-2026`, `c-rev-bridge-closes-fy2025`). Only the release
     lacks one.
   - **Still missing:**
     - "Other, including intercompany eliminations" is +$812 million in FY2025 (`k25-rev-bridge-other-fy2025`), with no
       further explanation;
     - no margin is given on Atlantic Copper's revenue growth (+$479 million in Q3 2026), only that its purchase costs
       rose (`q3-p-cost-drivers`);
     - there is no matching bridge for operating income or operating cash flow.
2. **No bridge for the operating-cash-flow sensitivity.** The company gives $75 million per $0.10 a pound for a Q4 2026
   price change (`r3-sens-ocf-copper`). It does not say how much is taken up by royalties, profit sharing, taxes or
   provisional-pricing timing.
3. **No split of the mud-rush idle costs into cash and non-cash.** Of the idle facility, recovery and restoration costs
   ($244 million in Q3 2026, `r3-idle-costs-q3-2026`), how much was paid in cash in the period is not stated.
4. **No fixed and variable cost split** at any division, so operating leverage cannot be measured.
5. **No volume path for the growth projects together.**
   - Bagdad now has a target start (mid-2030) and a long-term annual rate, but no year-by-year ramp (`nr-p-schedule`).
   - El Abra and Kucing Liar have only capital estimates and conditions (`mechanisms.md`, section 7).
6. **Net debt excluding PTFI downstream debt** is given at both dates, by different reports.
   - 2025-12-31: $2,320 million (10-K, `k25-net-debt-ex-ptfi-downstream-2025-12-31`).
   - 2026-09-30: $1,826 million (release, `r3-nd-net-debt-ex-2026-09-30`).
   - Both use the company's definition, with downstream debt of $3,235 million and $3,237 million respectively. The
     comparison holds as long as the definition is unchanged, and neither report says it changed.
7. **Two figures for open provisionally priced copper, in each period, with different scopes.**
   - At 2026-09-30:
     - the MD&A gives 239 million lb, or 134 million lb net of intercompany sales and noncontrolling interests, at $6.55
       (`q3-provisional-cu-open-2026-09-30`, `q3-provisional-cu-open-net-nci-2026-09-30`);
     - Note 5 gives 256 million lb of copper embedded derivatives at a contract price of $6.34
       (`q3-embedded-cu-open-2026-09-30`, `q3-embedded-cu-contract-price-2026-09-30`).
   - At 2025-12-31: 152 million lb net (`k25-provisional-copper-pounds-2025-12-31`) against 365 million lb in the
     derivatives note (`k25-embedded-derivative-copper-open-pounds-2025-12-31`).
   - The reports do not reconcile the pairs. Use the MD&A figure with its own sensitivity (`r3-provisional-sens`), and
     never mix the two.
8. **The 10-Q and the release show different 2025 operating cash flows, without comment.**
   - The 10-Q's figures are $25 million lower (`c-ocf-difference-9m-2025`, `c-ocf-difference-q3-2025`).
   - In the 9M 2025 column, accounts receivable in operating activities and "Other, net" in investing activities
     differ by the same amount.
   - Neither document mentions the difference or calls it a restatement. Both figures are kept (`comparison.md`).
9. **Small inconsistencies inside the 10-K**, recorded by the extraction and not resolved:
   - U.S. copper sales for 2025 are 1,296 million lb in the operating data (`k25-us-copper-sales-fy2025`) and 1,301 in
     the unit-cost table (printed pages 99–100);
   - 2023 export duties are $324 million in one note and $307 million in another;
   - South America's 2026 sales outlook is "1.1 billion" in the text and 1,080 million lb in the outlook table
     (`k25-outlook-copper-sales-south-america-fy2026`).
10. **The 10-K's ownership table** (printed page 2) did not come through in the page text, so ownership was taken from
    the mine descriptions and the notes (`k25-ownership-table-note`). The figures agree with the release.
11. **Tax assessments.** PTFI received about $740 million of assessments for 2023 in October 2026 and plans to object
    (`q3-p-tax-assessments-2023`). No provision or expected outcome is stated, so the cash effect is unknown.
12. **Gold export permission.** Whether PTFI can export refined gold without the 10% duty is unresolved
    (`r3-p-gold-export`). The Q4 2026 gold sales outlook (300 thousand ounces) depends on it in part, and the release
    gives no figure for the effect.
13. **PTFI's dividends to FCX in 2026, and PTFI's cash.**
    - The 10-Q attributes the 9M 2026 distributions to noncontrolling interests to Cerro Verde
      (`q3-p-nci-distributions`). It does not give PTFI's dividends to FCX for 2026. The 10-K gave $1.0 billion for 2025
      (`k25-ptfi-dividends-to-fcx-fy2025`).
    - No cash balance is given for PTFI alone. Cash at international operations ($2.0 billion at 2026-09-30,
      `q3-cash-international-2026-09-30`) is not split by subsidiary.
    - So the parent's 2026 receipts from PTFI, and whether PTFI built up cash, are unknown here.
14. **Bagdad: what the documents leave open.**
    - **The updated capital expenditure outlook is not published yet.** The company says the planned spending will be
      added to an updated outlook (`nr-p-discretionary`). The $4.4 billion 2026 outlook predates the approval, though
      it includes early works at Bagdad (`q3-p-bagdad-early-works`).
    - **Scope of the cost change.** The 10-K's $3.5 billion and the later $4.5 billion use different wording
      (`c-bagdad-capex-estimate-change`). No document says whether the scope changed.
    - **Undefined terms and missing bases:**
      - "incentive price" (February, October) and "break-even economics" (November) are not defined;
      - the 20% unit cost reduction has no base level or year (`nr-bagdad-uncc-reduction`);
      - "tons per day" does not say short or metric tons (`nr-bagdad-capacity-increment`);
      - the copper-equivalent grade does not give its conversion prices (`nr-bagdad-reserve-grade`).
    - **No ramp.** The release gives the long-term annual rate and the first production date, but no year-by-year path
      from mid-2030.

## C. Not collected in this stage (outside the approvals)

1. **The Q3 2026 conference-call slides and webcast.** The slides are exhibit 99.2 to the Form 8-K of 2026-10-27;
   they were not retained.
2. **Q1 and Q2 2026 reports**, which would give the quarterly path of the ramp-up (Q4 2025, Q1, Q2 and Q3 2026).
3. **Market data:** share price, share count history, consensus estimates, copper forward curve. These belong to the
   valuation stage, and some (consensus) are paid or restricted.
4. **Peers** (Southern Copper is already retained for the copper thesis, from its 10-K only).

The company's news release of 2026-11-04 on Bagdad, listed here in the first version, has been collected since. It is
read from its SEC copy, exhibit 99.1 to the Form 8-K of 2026-11-04.

## D. Questions to follow

1. **How much of the 2026 operating cash flow outlook depends on the fourth quarter's gold sales?** The outlook implies
   about $2,976 million of operating cash flows in Q4 2026 (`c-q4-ocf-implied`), with gold sales nearly tripling
   from Q3. What happens if the export question delays them?
2. **When does working capital turn back into cash?** 2026 production exceeds sales by about 100 million pounds of
   copper and 70 thousand ounces of gold (`r3-p-wc-deferral`). Does the release of that inventory fall in 2027?
3. **How do unit costs behave as Grasberg ramps to 80% and then 100%?** Idle facility costs end when operations
   return to normal capacity (`r3-p-idle-costs`). What do unit net cash costs look like on the restored volume? The
   company states one 2026 figure ($1.90, `r3-out-unc-fy2026`) and no 2027 figure in these documents.
4. **What did PTFI pay out in 2026, to FCX and to its other shareholders?**
   - Distributions to noncontrolling interests halved, from $1,274 million to $625 million (`r3-cf-dist-nci-9m-2026`),
     and the 10-Q names Cerro Verde for 2026 (`q3-p-nci-distributions`).
   - FCX's own PTFI dividends were $1.0 billion in 2025 (`k25-ptfi-dividends-to-fcx-fy2025`). The 2026 figure is not
     given; the full-year 10-K for 2026 may give it.
   - Dividends from subsidiaries that are not wholly owned "are shared with other equity owners"
     (`k25-holding-company-dividends-shared`).
5. **What would the 2042 change in PTFI ownership (48.76% to about 37%, `r3-p-mou`) do to attributable cash flows?**
   This is a valuation-stage question.
6. **The U.S. copper price premium.** The COMEX average ($6.48) was above the LME average ($6.40) in Q3 2026. How much
   of the U.S. realized price depends on that spread, and on U.S. trade policy? The documents give no figure. Bagdad's
   added pounds would be U.S. pounds, so the question grows with it.
7. **What does the company's own bridge between its two 2026 copper sensitivities look like?** February gave $330
   million per $0.10 for the whole year at $5.00 (`k25-sensitivity-ocf-copper-fy2026`). October gave $75 million for
   a Q4 change at $6.50 (`r3-sens-ocf-copper`). Ask how much of each is price-linked costs and taxes, and how much is
   settlement timing. Do not infer it.
8. **When do idle facility costs stop?** The 2026 outlook for PTFI idle costs rose from $0.9 billion (February,
   `k25-idle-facility-costs-outlook-fy2026`) to $1.2 billion (`q3-outlook-idle-costs-fy2026`). The costs end when
   operations return to normal capacity, which the company now expects near year-end 2027 (`r3-p-ramp-up`).
9. **Capital allocation with Bagdad approved.**
   - Net debt excluding project debt is $1.8 billion (`r3-nd-net-debt-ex-2026-09-30`), below the $3–4 billion target.
   - Bagdad's spending is classified as discretionary (`nr-p-discretionary`). On the company's shares, about $0.9
     billion falls in 2027 and $1.35–1.575 billion in 2028 (`c-bagdad-funding-2027`, `c-bagdad-funding-2028-low`,
     `c-bagdad-funding-2028-high`, this project's arithmetic).
   - Under the policy (`r3-p-financial-policy`), how do the 50% framework and discretionary growth capital share the
     cash? The updated capex outlook should answer part of it.
10. **What does "break-even economics at about $4.00" mean against the earlier "incentive price of about $4.00"?** Ask
    whether it is the same measure under a new name, or a different test.

## E. Left unchanged on purpose

- **The copper thesis and the copper calculator were not updated.** The thesis documents do not name Bagdad. The
  calculator carries Bagdad figures from the 2025 10-K:
  - about $3.5 billion of capital;
  - 200 to 250 million pounds a year;
  - an incentive price of about $4.00;
  - a decision expected during 2026.

  These are in the calculator's inputs (`content/tools/copper-coverage/inputs.json`) and its project list
  (`second_order/copper_producers.py`). The company's later statements differ: $4.5 billion, about 225 million pounds, a break-even price
  of about $4.00, and an approved project. Whether and how to update them is the owner's decision. Nothing outside
  `research/fcx/` was changed in this round.
