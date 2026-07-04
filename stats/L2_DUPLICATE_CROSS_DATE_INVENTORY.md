# L2 duplicate / cross-date same-story inventory (read-only)

**Status:** read-only inventory. No event row was edited, no date or ticker was
changed, no status was changed, and `events.db` was opened via SQLite `mode=ro`
only. Its hash is verified unchanged before and after this pass. This note is a
pre-policy census of the duplicate / cross-date same-story candidates the L1A/L1B
work surfaced; it decides nothing and mutates nothing. Any collapse policy is
deferred to the L2 policy memo and its impact probe.

## 1. What a reviewer should take away first

- **These rows are already inside one K2 cluster; the open question is counting,
  not grouping.** K2 groups the 86 accepted track-record rows into **7** descriptive
  market-story clusters, and every candidate row below already sits in the 79-row
  mega-cluster **c01**. So K2's *cluster count* already treats each of these
  stories as one story. What is still counted several times is the **nominal row
  count** (the 86 track-record rows, the 79 in c01, and the per-outcome
  support/contradiction/unresolved split inside c01).
- **The defect is cross-date re-ingestion the same-date detectors cannot see.**
  The exact `(headline, event_date)` duplicate detector finds only **one** cluster
  in the entire 180-row archive (`[302, 315]`, an unrelated 2023 FTC-Amazon pair);
  the C4 `thread_independence` layer links only same-date collisions. The rows
  below are the **same news story re-saved one to four days apart**, usually under
  a different primary ticker and sometimes with the opposite outcome label, so
  neither existing lens flags them.
- **Nine candidate groups, 22 rows.** All 22 are accepted track-record rows, all
  in c01, all with an event-study readout. Collapsing any group would reduce the
  nominal track-record and coverage denominators and shrink c01; it would **not**
  change the K2 cluster count (they are already merged).
- **Three groups carry an outcome conflict** (30/42, 26/48/61, and the OPEC saga
  39/53/54/64/70): one story currently contributes both a support and a
  contradiction to the ledger. These are the highest-consequence and the least
  safe to collapse without a policy decision on which observation survives.
- This inventory is descriptive only. It is **not** evidence of any mechanism, not
  a significance claim, not an FDR update, and it proposes no mutation SQL.

## 2. Method and denominators

- **Source of rows.** The candidate groups are the cross-date same-story pairs and
  sagas already named in `stats/L1_ANCHOR_REPAIR_BATCH.md` (sections 3 and 5) and
  source-verified for the first batch in `stats/L1B_REPAIR_PREVIEW.md` (section 5).
  This note re-queries the live archive read-only to attach each row's current
  date, headline, stage, primary ticker, outcome, readout availability, family
  lens, and c01 membership.
- **Two existing duplicate lenses, and why they miss these rows.**
  1. `scripts/duplicate_event_cluster_report.py` groups rows with an identical
     `(headline, event_date)` pair. Live, it returns **1** cluster archive-wide
     (`[302, 315]`); every candidate group below has copies on *different* dates,
     so it catches none of them.
  2. The C4 event-date-quality `thread_independence` layer links same-date
     collisions (e.g. the already-linked 53/54 pair). K2 consumes those links as
     its Rule 3. It does not reach across ingestion dates.
- **K2 already merges these by date/ticker chaining.** K2 Rule 1 (shared event
  date) and Rule 2 (same primary ticker within a 20-day window) chain the
  re-ingestions into c01. So the **descriptive cluster count already reflects one
  story**; the duplicate policy question is whether to also adjust the row-level
  denominators and the c01 outcome split.
- **Denominator ledger (live, unchanged).** archive **180** -> accepted coverage
  **94** -> accepted track-record **86** -> event-study **78 / 94** -> staged
  **13** (excluded). K2: **86** rows -> **7** clusters; c01 = **79** rows with a
  42 / 8 / 29 support / contradiction / unresolved split. The pools stay separate:
  no Phase 1 / Phase 2 q-value or denominator is touched here.
- **Representative-case exposure.** Two candidate rows anchor walkthrough surfaces:
  **61** is an F1 / K2 representative case (an N1 anchor), and **30** is the
  mechanism-family-inventory representative for `geopolitical_conflict_context`.
  Collapsing their groups would touch representative selection and is called out
  below.

## 3. Candidate group table

Headlines are ASCII-folded and shortened. `out` = canonical any_support outcome
(sup / con / unr). All rows are accepted, in c01, and event-study-available.
`class` is this note's descriptive classification (section 5 defines the buckets).

| group | ids (date) | short headline | tickers | out (sup/con/unr) | family lens | class |
| --- | --- | --- | --- | --- | --- | --- |
| G1 fighter-jet | 30 (04-05), 42 (04-06) | US fighter jet shot down over Iran | XOM ; LMT | con ; sup | geopolitical | same-story, outcome conflict |
| G2 Artemis | 2 (04-04), 49 (04-06) | Artemis II crew halfway to Moon | LMT ; DRIV | sup ; sup | unclassified | same-story + ticker noise |
| G3 Barnsley | 9 (04-05), 51 (04-06) | Two arrested after Barnsley collision | DRIV ; DRIV | sup ; sup | unclassified | ticker noise + same-story |
| G4 OPEC saga | 39 (04-05), 53 (04-06), 54 (04-06), 64 (04-08), 70 (04-09) | OPEC members discuss / agree extend output cuts | XLE x3 ; XOM x2 | con ; sup ; sup ; sup ; sup | supply_shock | same macro saga, outcome conflict |
| G5 tanker | 40 (04-05), 44 (04-06) | Petronas tanker with Iraqi crude via Hormuz | BDRY ; BDRY | sup ; sup | supply_shock | near-exact cross-date copy |
| G6 Foxconn | 25 (04-05), 50 (04-06) | Foxconn Q1 revenue jumps, cautions geopolitics | INDA ; GLD | sup ; sup | unclassified | same-story, attribution split |
| G7 FirstFT-Hormuz | 43 (04-06), 60 (04-08) | Trump threatens Iran power plants unless Hormuz reopens | XLE ; XOM | sup ; sup | unclassified | same-story, attribution split |
| G8 China-refiners | 16 (04-05), 72 (04-09) | China calls for independent refiners amid war | XLE ; VLO | sup ; sup | geopolitical | same-story, attribution split |
| G9 coal | 26 (04-05), 48 (04-06), 61 (04-08) | How Trump's Iran war makes world reliant on coal | BTU x3 | sup ; sup ; con | geopolitical | same-story x3, outcome conflict |

Headline note: within a group the stored headlines are byte-identical except G1
(row 30 carries a trailing "- Reuters", row 42 does not) and G4 (row 53 reads
"agree to extend voluntary oil output cuts"; 39/54/64/70 read "AP News: OPEC
members discuss extending output cuts").

## 4. Group-by-group notes

- **G1 fighter-jet (30, 42).** Same F-15E shootdown over Iran. L1B-0 web-sourced
  the true incident date as **2026-04-03**; row 30 was saved 04-05 (XOM,
  contradiction) and row 42 04-06 (LMT, support). One incident currently
  contributes both a support and a contradiction from two different windows.
  Collapsing would remove that double-count but must decide the surviving outcome
  and date, and 30 is the family-inventory representative for
  `geopolitical_conflict_context`. **Safe to collapse only after the surviving
  observation is chosen.** Denominator touched: accepted 86, coverage 94, c01 79,
  and the c01 support/contradiction split.
- **G2 Artemis (2, 49).** Identical headline (crewed lunar milestone, true date
  2026-04-04), saved 04-04 (LMT) and 04-06 (DRIV), both scored support, both with
  "insufficient" mechanism text. Not a market event for either ticker; the tickers
  are default-attribution noise. **Same-story determination is unambiguous.**
  Collapsing removes one support row and one noise ticker. Denominator touched:
  86 / 94 / c01 79 and the support count (-1).
- **G3 Barnsley (9, 51).** Identical headline (UK local-crime item), saved 04-05
  and 04-06, both DRIV, both support. No market mechanism; DRIV is auto/EV-ETF
  default-ticker noise. **Same-story unambiguous; attribution is noise on both.**
  Collapsing removes one support row. Denominator touched: 86 / 94 / c01 79 and
  the support count (-1).
- **G4 OPEC saga (39, 53, 54, 64, 70).** One OPEC+ output-cut decision (L1B-0
  sourced the meeting to 2026-04-05) re-saved five times across 04-05..04-09.
  53/54 are already C4-linked same-date; 64/70 escaped the same-date rule; 39 is
  the earliest. Outcome labels flip: 39 is a contradiction, the other four are
  support. Collapsing five rows to one cartel-decision observation is the largest
  single reduction here, and it changes the c01 outcome split (removes one
  contradiction and up to three supports). **Not safe to collapse without a
  policy decision on the surviving outcome.** Denominator touched: 86 / 94 / c01
  79 and the support and contradiction counts.
- **G5 tanker (40, 44).** Byte-identical headline, same primary ticker (BDRY),
  same outcome (support), same family (supply_shock), saved 04-05 and 04-06. This
  is the closest thing to an exact duplicate in the set: it differs only by the
  ingestion date. **Lowest-ambiguity collapse.** Denominator touched: 86 / 94 /
  c01 79 and the support count (-1). True event date not yet web-sourced (batch 2).
- **G6 Foxconn (25, 50).** Byte-identical headline, saved 04-05 and 04-06, both
  support, but **different primary tickers** (INDA vs GLD). Same-story is clear
  from the identical headline; which ticker attribution survives a collapse is a
  separate ruling. Denominator touched: 86 / 94 / c01 79 and the support count.
  True date not yet sourced (batch 2).
- **G7 FirstFT-Hormuz (43, 60).** Byte-identical headline, saved 04-06 and 04-08,
  both support, different tickers (XLE vs XOM). Same story; attribution split.
  Denominator touched as G6. True date not yet sourced (batch 2).
- **G8 China-refiners (16, 72).** Byte-identical headline, saved 04-05 and 04-09
  (a four-day span), both support, both `geopolitical_conflict_context`, different
  tickers (XLE vs VLO). Same story; attribution split; widest date gap in the set.
  Denominator touched as G6. True date not yet sourced (batch 2).
- **G9 coal (26, 48, 61).** Byte-identical headline ("How Trump's Iran war could
  make the world more reliant on coal"), saved 04-05 / 04-06 / 04-08, all primary
  BTU, all `anticipation` stage. 26 and 48 are support; **61 is a contradiction**
  and is an F1 / K2 representative case (N1 anchor). Collapsing three copies to one
  story changes the c01 outcome split and touches a representative walkthrough.
  **Not safe to collapse without deciding the surviving outcome and preserving the
  representative case.** Denominator touched: 86 / 94 / c01 79 and the outcome
  split.

## 5. Buckets

- **Exact duplicates (same headline AND same date).** None among these groups. The
  only exact `(headline, event_date)` pair archive-wide is `[302, 315]` (2023
  FTC-Amazon), which is unrelated to the c01 track record.
- **Same story across ingestion dates.** All nine groups. Each is one news story
  re-saved on consecutive or near-consecutive dates; G5 (tanker) is the nearest to
  an exact copy (same ticker and outcome, differs only by date).
- **Same macro saga, potentially distinct rows.** G4 (OPEC saga) is the one group
  where "one decision, one observation" is the L1B-0 reading, but a reviewer could
  argue that 39 (discuss) vs 53 (agree) reflect two reporting moments of the same
  decision. It is still one cartel action; the safest reading is one observation.
- **Ticker-attribution noise.** G2 (Artemis: LMT/DRIV) and G3 (Barnsley: DRIV) are
  non-market general-news rows carrying default tickers; the attribution, not just
  the duplication, is the defect. G6/G7/G8 carry a milder version: real market
  stories whose duplicate copies disagree on the primary ticker.
- **Insufficient / needs external source.** No group is fully insufficient, but the
  four batch-2 groups (G5, G6, G7, G8) have **not** been web-sourced to a true
  event date yet; their same-story status is decidable from stored fields, but a
  source-pinned canonical date is not.

## 6. Safe-to-collapse candidates

Groups where all members share one outcome label, so collapsing to a single
observation is unambiguous about the surviving label (it still reduces the nominal
count; it introduces no outcome-bookkeeping ambiguity):

- **G2 Artemis (2, 49)** - both support; non-market; tickers are noise.
- **G3 Barnsley (9, 51)** - both support; non-market; DRIV noise.
- **G5 tanker (40, 44)** - both support; same ticker (BDRY); nearest to an exact
  copy.

Even these change the support count and c01 size; "safe" means unambiguous, not
zero-impact. The quantitative effect is in the L2 impact probe.

## 7. Must-not-collapse-yet candidates

Groups where collapsing changes the support / contradiction / unresolved mix, so a
policy must first decide which observation survives (and, where noted, preserve a
representative case):

- **G1 fighter-jet (30, 42)** - support vs contradiction; 30 is the geopolitical
  family-inventory representative.
- **G4 OPEC saga (39, 53, 54, 64, 70)** - contradiction (39) vs four supports;
  largest single reduction.
- **G9 coal (26, 48, 61)** - two supports vs a contradiction; 61 is an F1 / K2
  representative case.

## 8. Needs-source / human-review candidates

Groups whose same-story status is clear from identical stored headlines, but whose
true anchor date is not yet web-sourced and whose surviving ticker attribution is
unresolved (real market stories, saved under conflicting tickers):

- **G6 Foxconn (25, 50)** - INDA vs GLD.
- **G7 FirstFT-Hormuz (43, 60)** - XLE vs XOM.
- **G8 China-refiners (16, 72)** - XLE vs VLO.

These need the gated batch-2 source pass (true date) and an attribution ruling
before any collapse; they are not blocked on the same-story determination itself.

## 9. What an L2 policy must decide before mutation

1. **Collapse vs annotate.** Whether cross-date same-story members are physically
   collapsed (one surviving observation, siblings marked duplicate-deferred) or
   only annotated / linked while all rows are preserved.
2. **Which observation survives, and its outcome.** For the outcome-conflict groups
   (G1, G4, G9), the surviving label is a bookkeeping decision, not a computation.
   Forcing coherence by changing an outcome to match is out of bounds.
3. **Which denominator changes.** Whether a collapse reduces the accepted
   track-record (86) and coverage (94) counts, or only a separate
   "duplicate-adjusted" descriptive count that leaves the archive denominators
   intact. The K2 cluster count (7) does not change either way.
4. **Attribution ruling.** For G6/G7/G8 (and the noise tickers in G2/G3), which
   primary ticker - or "no market primary" - survives a collapse.
5. **Representative-case preservation.** How collapsing G1 (row 30) and G9 (row 61)
   preserves the walkthrough / family-inventory representative selection.
6. **Readout preservation.** Every candidate row has an event-study readout; the
   policy must state whether collapsed siblings' readouts are retained as context
   or dropped, and never silently recompute event-study math.
7. **Provenance.** No row may be deleted without a preserved before/after record,
   per the Phase-K correction convention.

## 10. Guardrails and non-claims

- This inventory **repairs nothing** and proposes no mutation SQL; it is a census.
- Collapsing a duplicate does **not** prove or disprove any mechanism; it stops one
  event from being counted several times. It is a legibility and counting decision.
- A duplicate-adjusted count is **descriptive only**; it is not an effective sample
  size, not a p-value, not an FDR pool, and authorizes no pooling.
- The closed Phase 1 / Phase 2 pools are neither read nor touched; their
  denominators stay separate and unchanged.
- No family-level inference; family lenses are context columns only.
- Outcome labels are the canonical descriptive any_support vocabulary; a collapse
  must never change an outcome to force coherence.
- Not a trading, prediction, or recommendation surface, and it says nothing about
  future returns of any asset.

## 11. Reproduction commands (read-only)

```
# K2 market-story clusters (c01 membership, outcome split)
python scripts/effective_independent_evidence_report.py --db-path events.db --json

# same-date exact (headline, event_date) duplicate detector
python scripts/duplicate_event_cluster_report.py --db-path events.db --json

# per-candidate fields (read-only), e.g. for the 22 candidate ids:
#   SELECT id, event_date, stage, headline, market_tickers, mechanism_family
#   FROM events WHERE id IN (2,9,16,25,26,30,39,40,42,43,44,48,49,50,51,53,54,60,61,64,70,72)
```

- Database access: `events.db` opened via SQLite `mode=ro` only; SHA-256 verified
  unchanged before and after this pass. `price_cache.db` not opened. No provider,
  API, network, `/analyze`, fetch, or backfill call was made.
- Source artifacts read: `stats/L1_ANCHOR_REPAIR_BATCH.md`,
  `stats/L1B_REPAIR_PREVIEW.md`, `stats/L1B1_TEMP_DB_PROOF.md`,
  `stats/L1B2C_LIVE_REPAIR.md`, `stats/L1B2C0_TEMP_DB_PROOF.md`,
  `stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md`.
