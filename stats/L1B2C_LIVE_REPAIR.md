# L1B-2C live split-date anchor repair - 154 / 160 with cluster restatement

**Status:** live `events.db` mutation plus a coordinated restatement, applied and
verified. This slice corrected two no-ticker anchor dates in the live archive
(154 -> 2026-04-23, 160 -> 2026-04-24) and then restated every current reviewer
surface that depended on the c01 cluster headline. It was taken only after the
L1B-2C-0 split-date temp proof and a timestamped backup. `price_cache.db` was not
touched.

## 1. What a reviewer should take away first

- **The live repair was limited to rows 154 and 160.** The only fields written to
  the database were their two `event_date` values.
- **Exact changes:** 154 `2026-04-29 -> 2026-04-23`, 160 `2026-04-29 -> 2026-04-24`.
  Both remain no-ticker, no-readout, outcome `unresolved`.
- **K2 changed from 86 / 5 / 81 to 86 / 7 / 79.** The two rows left the c01
  mega-cluster; because their corrected dates differ (2026-04-23 vs 2026-04-24)
  and no other accepted row sits on either date, **they became two separate
  singleton clusters** (c06 at 2026-04-23, c07 at 2026-04-24), not a shared pair.
- **No denominators, outcomes, tickers, or readout availability changed.** The
  funnel stays 180 / 94 / 86 / 78 / 13; c01's support and contradiction counts are
  unchanged (only its unresolved count drops by the two rows that left).

## 2. Live mutation scope

- **Included rows:** 154, 160.
- **Excluded rows:** 2, 7, 9, 29, 30, 38, 39, 42, 46, 49, 153, 239 (none touched;
  239 remains at its L1B-2A anchor 2026-04-29).
- **Exact DB fields changed:** `events.event_date` on two rows only -
  `154: 2026-04-29 -> 2026-04-23` and `160: 2026-04-29 -> 2026-04-24`. Each update
  was guarded with `WHERE id=? AND event_date='2026-04-29'` inside `BEGIN
  IMMEDIATE` (rowcount 1 each). A full-table before/after comparison against the
  backup confirmed exactly rows 154 and 160 changed and `event_date` was the only
  differing field on each.
- **No ticker / outcome / readout changes.** No ticker was added; both stay
  `unresolved`; both keep an unavailable event-study readout (no assigned market
  asset). Their anchor-quality labels are unchanged (154 `manual_review_needed`,
  160 `partial_anticipation`).
- **Provenance / correction records:** none added in the database. As established
  in L1B-2A, `event_provenance` is an intake-only table and `event_hygiene` is a
  corpus-status override; neither cleanly hosts a post-hoc anchor-date correction.
  The explicit before/after correction lives in this committed note.

## 3. Source basis and date gate

- **Row 154 -> 2026-04-23.** The L1B-2B exact-date gate found 154's 2026-04-24 was
  only approximate; the free-public recheck put the matching OCCRP and Guardian
  coverage of the UK / Kyrgyzstan sanctions-letter story at **2026-04-23**. 154 is
  treated as pinned to 2026-04-23.
- **Row 160 -> 2026-04-24.** L1B-0 recorded an exact 2026-04-24 (the France 24
  story this row mirrors is dated 2026-04-24, with a dated source URL); this passed
  the L1B-2B exact-date gate.
- No new browsing was required; the source record is L1B-0, the L1B-2B gate note,
  and the L1B-2C-0 temp proof. No paid API, market-data provider, `/analyze`,
  fetch, or backfill was used.

## 4. Before / after table

| id | old event_date | new event_date | ticker/asset | readout avail (before -> after) | outcome (before -> after) | cluster (before -> after) | denominator impact |
|---|---|---|---|---|---|---|---|
| 154 | 2026-04-29 | 2026-04-23 | none (unchanged) | unavailable -> unavailable | unresolved -> unresolved | c01 (81) -> c06 (1) singleton | none |
| 160 | 2026-04-29 | 2026-04-24 | none (unchanged) | unavailable -> unavailable | unresolved -> unresolved | c01 (81) -> c07 (1) singleton | none |

Row 119, already at 2026-04-24, is a synthetic seed excluded from the accepted-86
lens, so it does not absorb 160; 154 and 160 each land alone.

## 5. Affected report and UI restatement

Reports were re-run against the mutated live DB; only surfaces whose content
actually changed were restated.

- **`stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md` (K2 exhibit) - REGENERATED.** This
  is the byte-match golden artifact; it was regenerated from the K2 generator and
  now matches the current render exactly. Headline **86 / 7 / 79**; singletons
  3 -> 5; "83 of 86 (96.5%)" -> "81 of 86 (94.2%)"; the c01 row becomes size 79,
  split **42 / 8 / 29**, ES **67 / 79**, 2026-04-29 x10; the c01 event-id list
  drops 154 and 160; the representative overlay shows 154 in singleton c06 and 160
  in singleton c07.
- **`frontend/src/lib/effective-independent-evidence.ts` - UPDATED.**
  `clusterCount 5 -> 7`, `largestClusterRows 81 -> 79`,
  `representativeCasesInLargest 14 -> 12`; `representativeCasesTotal 15` unchanged.
- **`frontend/src/components/pages/__tests__/evidence-overview.test.tsx` -
  UPDATED.** The three K2 cluster assertions now expect 7 clusters, largest 79, and
  12 / 15 representative cases (the loose `toContain` on "81" was corrected to "79"
  so it can no longer false-pass on the unrelated "81 market-scored snapshot").
- **`README.md` - UPDATED.** The reviewer-path line now reads 7 descriptive
  market-story clusters and a largest cluster of 79 rows.
- **`stats/C01_MARKET_NARRATIVE.md` - RESTATED (hand-authored).** c01 size 81 -> 79
  throughout; outcome split 42 / 8 / 31 -> **42 / 8 / 29** (both departing rows are
  unresolved); "31 of 32 unresolved" -> "29 of 32"; family-lens tally sanction
  4 -> 3 and ceasefire_deescalation 3 -> 2 (with "33 of the 81" -> "33 of the 79");
  no-primary-ticker rows "(none) 12" -> "(none) 10"; representative cases in c01
  14 / 15 -> 12 / 15 and readout-missing "14 of 81" -> "12 of 79"; the two rows
  removed from the "inside c01" table with a follow-up line placing them in
  singletons c06 / c07. The corpus totals (46 / 8 / 32, 86 rows) were left
  unchanged.

**Exact K2 headline after mutation:** 86 accepted rows / 7 clusters / largest 79.

**Exact Evidence Overview values after mutation:** accepted track-record rows 86;
descriptive market-story clusters **7**; largest cluster **79** rows;
representative cases in largest **12 / 15**.

**Denominators after mutation:** archive 180, accepted coverage 94, accepted
track-record 86, event-study available 78 / 94, staged candidates 13 - unchanged.

**Unchanged artifacts (and why):**
- **Reaction matrix, representative-case expansion, event-date-quality
  distribution exhibits** - 154 and 160 display only their anchor-quality labels
  (unchanged) and an unavailable readout; none of these exhibits shows their event
  date or cluster, so their content is unchanged.
- **`frontend/src/components/pages/evidence-overview.tsx`** - it reads the cluster
  numbers from the lib constants, so it updates automatically; no edit was needed.
  (Its separate "81 market-scored snapshot" wording is the Phase-1 lens, a
  different 81, and was correctly left alone.)

**Disclosed out-of-scope drift (not fixed here):** the row 239 date was corrected
to 2026-04-29 inside the C01 representative table because that table was being
edited. Two other artifacts still carry 239's pre-L1B-2A date 2026-05-01 -
`stats/EXPANDED_CASE_NOTES.md` (its 239 dossier) and
`stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md` (family date-range endpoints) - as
a wider carry-over from L1B-2A's narrower scope. They are outside this slice's
surface and are flagged for a separate cleanup rather than expanded into here.

## 6. Verification

- **events.db SHA-256 before:**
  `d02601183e1d0bd9db18d257332eff8ae06637b972f5031d9a59f3d5eb09b4d8`.
- **events.db SHA-256 after:**
  `b950b22f10e8d660f08b98f61cf6589c5bdbde2b20477982a4453446ac5a7b98`.
- **Backup:** `<scratchpad>/events.db.backup.20260702T140315`, SHA-256
  `d02601183e1d0bd9db18d257332eff8ae06637b972f5031d9a59f3d5eb09b4d8` (equal to the
  pre-mutation live hash); outside git tracking, not staged.
- **price_cache.db before and after:**
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (0 bytes) -
  unchanged.
- **Row-level mutation check:** a full-table before/after comparison against the
  backup returned exactly `[154, 160]`; within each, only `event_date` differed.
- **Unselected-row no-change check:** no other event row changed; 239 remains at
  2026-04-29; the eight excluded rows are byte-for-byte unchanged.
- **Backend report tests:** `python -m unittest` on the four report modules -
  **141 tests, OK** (including the K2 committed-markdown byte-match golden test).
- **Frontend tests:** Evidence Overview suite **80 tests passed** at the new
  7 / 79 / 12 values; `npm run typecheck` clean; `npm run build` succeeded.
- **C01 cross-check:** every c01 figure in the narrative (size 79, split
  42 / 8 / 29) matches the regenerated K2 exhibit's authoritative c01 line; a
  post-edit completeness scan found no surviving 81 / 42-8-31 / 14-of / stale-239
  figures in the narrative.
- **git diff --check:** clean.
- **cp1252 / Windows-safe:** the changed markdown is cp1252-safe; L1B-2C introduced
  no new non-ASCII bytes.
- **Banned-framing:** the changed text carries no trading-signal, forecast,
  recommendation, or significance framing except in negated non-claims.
- **DB files staged:** none. `events.db`, `price_cache.db`, and the backup are
  git-ignored and were not staged.

## 7. Guardrails and non-claims

- Anchor repair improves the archive's date correctness and legibility; it does
  **not** create independent evidence, add a data point, or make any mechanism
  true.
- Splitting a mega-cluster into a smaller cluster plus singletons is a descriptive
  independence caution, not an inferential effective sample size; it neither proves
  nor disproves any mechanism.
- No p-value, no FDR update, no new pool, no score, no rank. Phase 1 and Phase 2
  pools were neither read nor changed.
- No family-level inference; family lenses are context only.
- Not a trading signal, not a forecast, not a recommendation, and nothing here
  speaks to the future returns of any asset.

## 8. Reproduction note

- **Backup + mutation:** `events.db` copied to
  `<scratchpad>/events.db.backup.20260702T140315` (hash verified equal to live),
  then two guarded statements inside one transaction:
  `UPDATE events SET event_date='2026-04-23' WHERE id=154 AND event_date='2026-04-29'`
  and
  `UPDATE events SET event_date='2026-04-24' WHERE id=160 AND event_date='2026-04-29'`
  (rowcount 1 each, committed). Row-level and price_cache checks followed.
- **Report regeneration / checks (against the live DB):**
  - `python scripts/effective_independent_evidence_report.py --db-path events.db`
    (K2 exhibit regenerated via `render_markdown(build_report(...))`)
  - `python scripts/case_library_reaction_matrix.py --db-path events.db --json`
  - `python scripts/representative_case_expansion_report.py --db-path events.db`
  - `python scripts/event_date_quality_distribution_report.py --db-path events.db`
- **Tests:** `python -m unittest tests.test_effective_independent_evidence_report
  tests.test_case_library_reaction_matrix
  tests.test_representative_case_expansion_report
  tests.test_event_date_quality_distribution_report` (141, OK); and, in `frontend/`,
  `npx vitest run src/components/pages/__tests__/evidence-overview.test.tsx`
  (80, passed), `npm run typecheck`, `npm run build`.
- No provider or market-data API call, no `/analyze`, no fetch or backfill, and no
  `price_cache.db` mutation was performed.
