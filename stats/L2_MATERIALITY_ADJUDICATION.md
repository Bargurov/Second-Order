# L2A-1 materiality adjudication (read-only)

**Status:** read-only adjudication. No event row was edited; no date, ticker,
outcome, or representative case was changed; no row was excluded or collapsed;
`events.db` was opened via SQLite `mode=ro` only and its SHA-256 is verified
unchanged before and after this pass. This note applies the archive-row ontology
to the nine L2 duplicate / cross-date groups and decides, from stored fields only,
which rows add materially new research information and which are re-ingestion
without new information. It decides nothing about the final L2 end state, moves no
denominator, and implements no metadata.

## 0. The ontology test applied here

One row = one dated research observation: a distinct event occurrence, or a
materially distinct event-mechanism-readout instance. A new ingestion timestamp
alone does not justify a new row. Same-story re-ingestion without new information
is a hygiene defect. Distinct developments within the same saga may remain
separate linked rows. A different primary ticker alone does not justify a separate
row unless it carries a materially distinct research hypothesis.

Each of the 22 candidate rows is classified as one of:

- **hygiene near-duplicate** -- re-ingestion of a story already recorded, adding
  no materially new information;
- **materially distinct -- keep linked** -- a distinct occurrence, development, or
  research hypothesis that earns its own row;
- **undecidable -- needs source** -- stored fields do not settle the call (an
  unsourced true date, an unresolved attribution, or an outcome conflict that a
  hygiene verdict would silently resolve).

## 1. What a reviewer should take away first

- **Three rows in fully-clean, un-flagged groups are firm hygiene defects: `49, 51,
  44`** (G2 Artemis, G3 Barnsley, G5 tanker) -- all support. **Five further rows lean
  hygiene but sit inside groups the operator flagged to hold** (G4, G6, G9):
  `50, 54, 64, 70, 48` -- each grounded in stored fields, none touching its group's
  held conflict or open question, so each is reported as leaning-hygiene, not forced
  closure. The eight support rows all sit inside c01; read against a
  distinct-observation lens (descriptive only, not applied here) they move distinct
  observations 86 -> 83 (firm) or -> 78 (with the held-group rows) and c01 support
  42 -> 39 or -> 34; contradiction (8) and unresolved (29) do not move.
- **Three groups are cleanly resolved from stored fields** (G2, G3, G5); **G6
  resolves on the specific ground that its later row records no mechanism** (so no
  attribution was forced); **G4 and G9 are partially resolved** (redundant
  re-ingestions decided, the outcome-conflict member held); **G1, G7, G8 remain
  undecidable** pending source work.
- **The support tally is what re-ingestion inflates.** All eight implicated hygiene
  rows, and the two lean-hygiene undecidable rows (42, 60), are support rows;
  the only contradiction in the candidate set that a hygiene reading would touch
  (61) is held open because it is an outcome conflict and a representative case.
- **No single duplicate-adjusted denominator is stated,** because five groups carry
  open source or policy questions. The defensible figure is a range (section 7).
- **A stored "insufficient" mechanism is decisive.** Several later re-ingestions
  carry the literal text "Insufficient evidence to identify mechanism"; by their own
  content they record no research observation, which settles their group without an
  attribution ruling (this is why G6 needs no source work, contrary to the earlier
  inventory's assumption).
- This is descriptive hygiene adjudication only. It is not evidence of any
  mechanism, not a significance claim, not an FDR update, and it authorizes no
  exclusion. Not a trading, prediction, or recommendation surface.

## 2. Method and grounding

- **Stored fields only.** For each of the 22 rows this note reads `headline`,
  `event_date`, `stage`, `market_tickers` (symbols, roles, direction tags),
  `mechanism_family`, and `mechanism_summary`, plus the derived primary ticker and
  the `any_support` outcome label as assembled by the live K2 loader
  (`scripts/effective_independent_evidence_report.py` `_assemble_rows`). No external
  source was consulted; no browse, no provider or market-data call.
- **Outcome is a readout, not a stored label.** The support / contradiction /
  unresolved label is `score_event_under_rule(tickers, "any_support")` -- a function
  of each row's ticker readout against SPY over the reaction window. This matters
  for the outcome-conflict groups: the same event and mechanism can read as support
  on one date-window and as a contradiction on another purely because the window
  moved. Such a window-driven flip is not, by itself, a materially new observation.
- **Baseline reconciled live (unchanged).** 86 accepted track-record rows; 7
  descriptive clusters; c01 = 79 with a 42 / 8 / 29 split; corpus 46 / 8 / 32; all
  22 candidates sit inside c01, each event-study-available. These match the impact
  probe exactly.
- **Stored duplicate flag observed.** The event-date-quality layer already labels
  rows 53 and 54 `duplicate_or_deferred` (a same-date collision); every other
  candidate carries `manual_review_needed` or `partial_anticipation`. That existing
  flag is used as corroboration for G4 only, not as the basis for any other verdict.

## 3. Per-group adjudication

Dates are 2026. `out` is the live `any_support` outcome. Verdict abbreviations:
**H** hygiene near-duplicate (firm, in an un-flagged group); **H*** the same
hygiene reading but held inside a group the operator flagged for hold, so it is not
presented as forced closure; **D** materially distinct -- keep linked; **U**
undecidable -- needs source. `H*` is a confidence annotation on the hygiene class,
not a fourth category.

| group | row (date, primary, out) | verdict | stored-evidence rationale |
| --- | --- | --- | --- |
| G1 fighter-jet | 30 (04-05, XOM, con) | D | Informative anchor: full Strait-of-Hormuz oil-supply mechanism; geopolitical family-inventory representative. |
| G1 | 42 (04-06, LMT, sup) | U | "Insufficient evidence to identify mechanism"; adds no mechanism. Distinctness rests only on a defense-tilted ticker set and a window-driven opposite outcome. A hygiene verdict would silently resolve the 30/42 outcome conflict; the canonical anchor for the one real incident needs the true date. |
| G2 Artemis | 2 (04-04, LMT, sup) | D | Informative anchor: carries the Artemis-program mechanism (LMT/NOC/BA). |
| G2 | 49 (04-06, DRIV, sup) | H | Byte-identical headline two days later; "Insufficient evidence"; default-noise tickers (DRIV/LIT); same outcome. No new information. |
| G3 Barnsley | 9 (04-05, DRIV, sup) | D | Earliest; canonical anchor. (Both members are non-market local-crime items with DRIV default-ticker noise; that attribution facet of 9 itself is a pre-existing corpus matter outside this pair.) |
| G3 | 51 (04-06, DRIV, sup) | H | Byte-identical headline +1 day; same ticker; both "Insufficient evidence"; same outcome. Adds nothing. |
| G4 OPEC saga | 39 (04-05, XLE, con) | U | Earliest "discuss / consider" moment; held as a separate linked row (not collapsed), but whether "discuss" and "agree" are two developments needs source (section 6); its contradiction outcome is preserved regardless. |
| G4 | 53 (04-06, XLE, sup) | U | "agree to extend" reads as a distinct development from "discuss" under the saga clause, so it is held linked pending source confirmation of that two-development reading. |
| G4 | 54 (04-06, XLE, sup) | H* | Same date as 53 but carries the older "discuss" headline (identical to 39); the event-date-quality layer already flags 53/54 `duplicate_or_deferred`. Re-ingestion, no new development; held-group. |
| G4 | 64 (04-08, XOM, sup) | H* | Identical "discuss" wire headline re-saved after the decision, same mechanism (XOM-vs-XLE is attribution only); leans hygiene, held pending G4's source decision. |
| G4 | 70 (04-09, XOM, sup) | H* | As 64, one day later. Same "discuss" headline; leans hygiene, held pending G4's source decision. |
| G5 tanker | 40 (04-05, BDRY, sup) | D | Earliest; canonical anchor. |
| G5 | 44 (04-06, BDRY, sup) | H | Byte-identical headline +1 day; same primary ticker (BDRY); both "Insufficient evidence"; same outcome. Nearest to an exact copy; adds nothing. |
| G6 Foxconn | 25 (04-05, INDA, sup) | D | Informative anchor: Foxconn tariff / cross-border-policy caution mechanism. |
| G6 | 50 (04-06, GLD, sup) | H* | Byte-identical headline +1 day; "Insufficient evidence"; tickers GLD/DRIV/LIT, with GLD (a loser in 25) re-tagged beneficiary behind no mechanism. Because 50 records no mechanism, the INDA-vs-GLD attribution question is moot -- 25 is the informative observation and 50 adds nothing; no attribution was forced. Held-group (G6 is a ticker-attribution group). |
| G7 FirstFT-Hormuz | 43 (04-06, XLE, sup) | D | Informative; Hormuz-chokepoint mechanism (XLE/TNK/STNG). |
| G7 | 60 (04-08, XOM, sup) | U | Byte-identical "FirstFT" newsletter headline two days later, but carries its own developed Hormuz-chokepoint mechanism (not insufficient); primary ticker differs (XOM vs XLE) with the same hypothesis. Leans hygiene (a daily newsletter re-captured), but settling that 60 is the same item -- not a distinct re-report -- and the attribution needs the item's publication date. Same outcome, so no conflict. |
| G8 China-refiners | 16 (04-05, XLE, sup) | D | Chinese-independent-refiner supply thesis (XLE/COP/OXY beneficiaries; BABA/FXI/KWEB losers). |
| G8 | 72 (04-09, VLO, sup) | U | Byte-identical headline four days later, but a genuinely different asset thesis -- US refiner margins (VLO/MPC/PSX) rather than 16's Chinese-refiner / China-equity framing. A materially distinct hypothesis on the same story may remain a separate linked row, so 72 leans keep; the true story date is needed to decide re-report vs re-ingestion. Widest date gap. |
| G9 coal | 26 (04-05, BTU, sup) | D | Earliest; fullest Iran-war-to-coal-reliance mechanism. |
| G9 | 48 (04-06, BTU, sup) | H* | Byte-identical headline +1 day; same ticker (BTU); same anticipation stage; same coal-reliance thesis; same outcome. No new development; held-group (G9 carries the 61 outcome conflict, which 48 does not touch). |
| G9 | 61 (04-08, BTU, con) | U | Byte-identical headline and identical BTU coal-reliance thesis; adds no new mechanism, but its outcome is a contradiction (a window-driven readout flip on the same ticker) and 61 is an F1 / K2 representative case. A hygiene verdict would silently resolve the outcome conflict and touch a representative case. |

## 4. Established hygiene-defect rows

Decided from stored fields; each is a re-ingestion of a story its group's anchor
already records, adding no materially new information. Two tiers, because five of
the eight sit inside groups the operator flagged to hold:

- **Firm, in fully-clean un-flagged groups (3, all support):** `49` (G2), `51` (G3),
  `44` (G5) -- byte-identical same-outcome re-ingestions of non-market or exact-copy
  items. This is exactly the impact probe's conservative set, now reasoned rather
  than mechanical.
- **Leaning hygiene, held inside flagged groups (5, all support):** `50` (G6),
  `54, 64, 70` (G4), `48` (G9). Each is grounded -- 50 records no mechanism (so no
  attribution was forced); 54 is already flagged `duplicate_or_deferred` by the
  event-date-quality layer; 64/70 repeat the "discuss" wire headline after the
  decision; 48 is a same-ticker, same-outcome, +1-day copy -- but each sits in a
  group named for hold (G4 / G9 outcome conflicts, G6 ticker-attribution), so none is
  presented as forced closure, and none touches its group's held conflict or open
  question.

These are adjudicated, not excluded. No row is removed here; the count effect below
is a descriptive reading, not an applied change.

## 5. Materially distinct observations (kept, linked)

Rows that earn their own place:

- Informative anchors of their groups: `2, 9, 25, 26, 30, 40, 43, 16`.
- **G4 `39` (discuss / consider) and `53` (agree to extend)** are held as two
  separate linked rows -- not collapsed -- but their two-development reading is
  itself pending source confirmation (section 6), so they are marked undecidable
  rather than firmly distinct. 39's contradiction outcome is preserved regardless.

## 6. Undecidable groups and the exact open question

- **G1 (30 / 42) -- outcome conflict.** 42 is information-empty (insufficient), so on
  content it adds nothing; but calling it hygiene would silently drop a support and
  leave 30's contradiction, resolving the conflict by fiat. **Open:** the true
  F-15E incident date and which observation (30 contradiction / 42 support) is the
  canonical anchor. **Requires source.**
- **G4 (39 / 53) -- development vs single decision.** 54/64/70 are decided (hygiene).
  **Open:** whether "discuss" (39) and "agree" (53) are two developments or one
  cartel action, and which outcome anchors the discuss thread (39 is a
  contradiction). **Requires source** (OPEC meeting timeline).
- **G7 (43 / 60) -- re-report vs re-ingestion.** Both carry developed mechanisms.
  **Open:** whether 60 is the same FirstFT newsletter item re-captured (leans
  hygiene) and the XLE-vs-XOM attribution. **Requires source** (item publication
  date / identity).
- **G8 (16 / 72) -- one story, two theses.** 72's US-refiner-margin thesis is a
  materially distinct hypothesis from 16's Chinese-refiner framing, so 72 leans
  keep. **Open:** the true story date, to decide distinct re-report vs re-ingestion.
  **Requires source.**
- **G9 member 61 -- outcome conflict + representative case.** 48 is decided
  (hygiene). 61 records no new mechanism (identical coal thesis) but carries a
  window-driven contradiction and is a representative case. **Open:** the surviving
  outcome for the coal thread and how 61 is preserved as a representative.
  **Does not require external source** -- the identical mechanism is visible from
  stored fields; this is a policy and representative-case decision, not a sourcing
  one.

## 7. Reconciliation to the impact probe, and the defensible ranges

The impact probe bounded the effect mechanically (keep the earliest row in each
group): conservative -3 (drop 49 / 51 / 44), worst-case -13. This adjudication
reads the same rows by information content and lands **between** those bounds:

| lens | rows treated as non-distinct | distinct observations | c01 support | c01 con / unr |
| --- | --- | --- | --- | --- |
| baseline (live, unchanged) | 0 | 86 | 42 | 8 / 29 |
| **this adjudication -- firm clean (G2/G3/G5)** | **3** (all support) | **83** | **39** | **8 / 29** |
| probe conservative (mechanical, same 3 rows) | 3 | 83 | 39 | 8 / 29 |
| **plausible hygiene-adjusted (+ 5 held-group H* rows: 50, 54, 64, 70, 48)** | **8** (all support) | **78** | **34** | **8 / 29** |
| unresolved sensitivity only (adds unresolved 42, 60, 61; 61 = a contradiction + representative case) | 11 | 75 | 32 | 7 / 29 |
| probe worst-case (mechanical) | 13 | 73 | 30 | 7 / 29 |

- **Distinct observations -- a strict hierarchy of decreasing confidence, not a
  central band:**
  - **83 -- firm:** after the three clear hygiene defects (49 / 51 / 44) only.
  - **78 -- plausible hygiene-adjusted:** adds the five held-group `H*` rows
    (50 / 54 / 64 / 70 / 48). A plausible reading, not a decided one -- these rows sit
    in groups flagged for hold.
  - **75 -- unresolved sensitivity only:** additionally removes the unresolved rows
    42, 60, and **61**. This is **not** a hygiene-adjusted count -- 61 is a
    contradiction and a representative case, and 42 / 60 are undecidable. It is a
    sensitivity floor this note does not endorse as a reading.
  - **73 -- mechanical worst-case sensitivity:** the probe's keep-earliest bound.
  Row 61 is **not** part of the firm (83) or the plausible hygiene-adjusted (78)
  count. All four figures sit inside the probe's 73 - 83 envelope.
- **c01 support follows the same hierarchy:** 39 firm (after the three clear defects)
  -> 34 at the plausible hygiene-adjusted reading (the five `H*` rows) -> 32 only under
  the unresolved-sensitivity floor. Corpus support 43 -> 38 -> 36. Contradiction stays
  8 through the firm and plausible readings and moves to 7 **only** at the
  unresolved-sensitivity floor, because that single contradiction is row 61; unresolved
  is 29 throughout.
- **Why the mechanical worst-case (73) over-counts hygiene:** it drops row 53
  ("agree", a distinct development) and row 72 (a distinct US-refiner thesis), both
  of which the content read keeps. The probe's conservative (83) under-counts,
  because it ignores 50 / 54 / 64 / 70 / 48, which are also information-empty
  re-ingestions.
- **No single duplicate-adjusted denominator is stated,** because G1, G4, G7, G8,
  and the G9 member 61 carry open source or policy questions. A range is the honest
  figure until those are settled.

## 8. Source work actually required next

- **Requires external source:** G1 (true F-15E date + canonical anchor), G4
  (OPEC discuss-vs-agree timeline + surviving outcome; the leaning-hygiene status of
  64 / 70 is contingent on this), G7 (FirstFT item identity / date), G8 (true
  China-refiner story date). These four are the only groups whose resolution depends
  on information not in the archive.
- **Does not require external source:** the eight established hygiene calls (decided
  now) and the G9 member 61 (a surviving-outcome policy plus representative-case
  decision, resolvable from stored fields and existing policy, not browsing).

## 9. What this note does not do (guardrails and non-claims)

- It **excludes, collapses, deletes, relabels, and re-dates nothing**, and changes
  no representative case; every row and its readout is intact.
- Adjudication is not correction: even the eight established defects remain in the
  archive. Any exclusion is a separate, explicitly gated decision and is not
  authorized here.
- Every count is **descriptive only** -- not an effective sample size, not a
  p-value, not an FDR figure, and it authorizes no pooling. The closed Phase 1 /
  Phase 2 pools are neither read nor touched.
- No outcome label was changed to force a group into coherence; no contradiction row
  (30, 39, 61) was hidden to make a story read as clean support.
- No mechanism is asserted or denied; family lenses are context only. Not a trading,
  prediction, or recommendation surface, and it says nothing about future returns of
  any asset.

## 10. Reproduction and state (read-only)

- **HEAD at adjudication:** `c730d2a` (main == origin/main, 0 / 0, tree clean).
- **events.db SHA-256:**
  `b950b22f10e8d660f08b98f61cf6589c5bdbde2b20477982a4453446ac5a7b98` -- verified
  unchanged before and after (opened `mode=ro`).
- **price_cache.db SHA-256:**
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, size 0 bytes
  -- not opened, unchanged.
- Stored fields per row read directly from `events`; outcome and primary ticker
  reconciled through `scripts/effective_independent_evidence_report.py`
  `_assemble_rows` (read-only). No new script was written; no `/analyze`, fetch,
  backfill, provider, or paid call was made.
- Source artifacts read: `stats/L1B_CLOSEOUT.md`,
  `stats/L2_DUPLICATE_CROSS_DATE_INVENTORY.md`,
  `stats/L2_DUPLICATE_POLICY_IMPACT_PROBE.md`,
  `stats/L2_DUPLICATE_POLICY_OPTIONS.md`.
