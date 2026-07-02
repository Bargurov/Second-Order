# L1B-2C-0 revised temp-DB proof - split-date 154 / 160 (temp copy only)

**Status:** revised temp-DB proof, not a live repair. Live `events.db` and
`price_cache.db` were not mutated. A byte-identical copy of `events.db` was made
outside git, the split-date corrections were applied to that copy only, and the
affected reports were re-run against the copy to show exactly what a later live
L1B-2C mutation would move. Nothing in the tracked archive was changed by this
task except this note.

## 1. What a reviewer should take away first

- **This is a revised temp-DB proof, not the live repair.** It supersedes the
  premise the L1B-1 temp proof used for these two rows.
- **The original shared-2026-04-24 premise is retired.** L1B-1 assumed 154 and 160
  would both move to 2026-04-24 and form one 2-row cluster. The L1B-2B exact-date
  gate then found 154's 2026-04-24 was only approximate, and a free-public recheck
  put 154 at **2026-04-23**, not 2026-04-24. The two rows therefore no longer share
  a date.
- **The tested scenario is split-date:** row 154 -> **2026-04-23**, row 160 ->
  **2026-04-24**. On the temp copy, each row lands alone, so they become **two
  separate singleton clusters**, not a shared pair.
- **The split-date scenario is safe enough for a later live L1B-2C mutation,
  conditional on a coordinated restatement.** No denominator, outcome, readout
  availability, or anchor-quality label changed. What does change is the K2 cluster
  headline: **86 / 5 / 81 -> 86 / 7 / 79**, with 154 and 160 leaving the c01
  mega-cluster into their own singletons. That change must be restated in the K2
  exhibit, the frontend effective-evidence constants and tests, the README line,
  and the C01 narrative in the same live slice.

## 2. Mutation scope tested

- **Included rows:** 154, 160.
- **Excluded rows:** 2, 7, 9, 29, 30, 38, 39, 42, 46, 49, 153, 239 (none touched).
- **Exact temp DB fields changed:** `events.event_date` on two rows only -
  `154: 2026-04-29 -> 2026-04-23` and `160: 2026-04-29 -> 2026-04-24`. A full-table
  before/after comparison confirmed exactly rows 154 and 160 changed and
  `event_date` was the only differing field on each.
- **No ticker / outcome / readout changes.** Both rows stay no-ticker (`[]`), stay
  outcome `unresolved`, and keep an unavailable event-study readout (no assigned
  market asset). Their anchor-quality labels are unchanged (154
  `manual_review_needed`, 160 `partial_anticipation`).

## 3. Source basis

- **Row 154 -> 2026-04-23.** The L1B-2B exact-date gate recorded that 154's
  2026-04-24 was approximate; a free-public recheck of the UK / Kyrgyzstan
  sanctions-letter story put the matching OCCRP and Guardian coverage at
  **2026-04-23**. This proof tests that recheck-supported date. (Whether 2026-04-23
  is treated as exact enough to mutate live is the gate decision for L1B-2C; it is
  a more specific date than the failed ~2026-04-24.)
- **Row 160 -> 2026-04-24.** L1B-0 recorded an exact 2026-04-24 (the France 24
  story this row mirrors is dated 2026-04-24, with a dated source URL). This passed
  the L1B-2B exact-date gate.
- No paid API, market-data provider, `/analyze`, fetch, or backfill was used; the
  source basis is the L1B-2B gate record and L1B-0.

## 4. Before / after table

Cluster notation "c01(81)" means the row sat in cluster c01 holding 81 rows.
Labels are the live `event_date_quality` classifications, re-run on the temp copy.

| id | old event_date | new event_date | anchor label (before -> after) | ticker/asset (before -> after) | readout avail (before -> after) | outcome (before -> after) | cluster (before -> after) | denominator impact |
|---|---|---|---|---|---|---|---|---|
| 154 | 2026-04-29 | 2026-04-23 | manual_review_needed -> manual_review_needed | none -> none (no ticker) | unavailable -> unavailable | unresolved -> unresolved | c01 (81) -> c06 (1) singleton | none |
| 160 | 2026-04-29 | 2026-04-24 | partial_anticipation -> partial_anticipation | none -> none (no ticker) | unavailable -> unavailable | unresolved -> unresolved | c01 (81) -> c07 (1) singleton | none |

154 lands alone at 2026-04-23 and 160 lands alone at 2026-04-24; no accepted
track-record row currently sits on either date (the archive row already at
2026-04-24, id 119, is a synthetic seed excluded from the accepted-corpus lens, so
it does not absorb 160). The two rows form two distinct singletons, not a pair.

## 5. Temp-DB impact summary

Reports were run against the temp copy before and after the split mutation (all
read-only, via `--db-path` / the report internals).

**K2 (effective independent evidence) - CHANGES:**

| measure | before | after |
|---|---|---|
| accepted track-record rows | 86 | 86 |
| market-story clusters | 5 | **7** |
| largest cluster size | 81 | **79** |
| singleton clusters | 3 | **5** |
| multi-row clusters | 2 | 2 |
| rows in multi-row clusters | 83 (96.5%) | **81 (94.2%)** |
| c01 size | 81 | **79** |
| c01 outcome split (S / C / U) | 42 / 8 / 31 | **42 / 8 / 29** |
| c01 event-study rows | 67 / 81 | **67 / 79** |
| top date 2026-04-29 | 12 rows | **10 rows** |
| representative cases in largest cluster | 14 / 15 | **12 / 15** |
| new clusters | - | **c06 = {154} @ 2026-04-23; c07 = {160} @ 2026-04-24** |

- **c01 before/after:** loses rows 154 and 160 (both `unresolved`), so its size
  drops 81 -> 79 and its unresolved count drops 31 -> 29; support (42) and
  contradiction (8) are unchanged. Its date range (2026-04-04 .. 2026-05-05) is
  unchanged.
- **New singletons/clusters:** 154 and 160 do **not** share a cluster; they form
  two separate one-row clusters at 2026-04-23 and 2026-04-24.
- **Denominators:** archive 180, accepted coverage 94, accepted track-record 86,
  event-study available 78 / 94, staged candidates 13 - all unchanged (no row was
  added, removed, or reclassified).
- **Case-library reaction matrix - UNCHANGED.** Rows 154 and 160 already show an
  unavailable readout and their anchor-quality labels are unchanged; the matrix
  shows no event date or cluster for them, and references no cluster count.
- **Representative-case expansion - UNCHANGED.** 154 and 160 display role, family,
  outcome (`unresolved`), event-study availability (false), and anchor label - none
  of which depend on the date value.
- **Event-date quality distribution - UNCHANGED.** The anchor-quality labels of 154
  and 160 do not change (the classifier keys on headline wording, not the date), so
  the histogram is identical.

## 6. Frontend / README / C01 restatement preview

These are the current values and what a later live L1B-2C mutation would need to
change. This temp-proof task edits none of them; the restatement belongs to the
live slice so all surfaces move together in one commit.

- **`frontend/src/lib/effective-independent-evidence.ts`** (current -> after):
  `clusterCount 5 -> 7`, `largestClusterRows 81 -> 79`,
  `representativeCasesInLargest 14 -> 12`; `representativeCasesTotal 15` unchanged.
  The Evidence Overview tests that assert these values would move with them.
- **`stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md`** (K2 exhibit, byte-match golden):
  regenerates to 7 clusters / largest 79 / singletons 5 / "81 of 86 (94.2%)"; the
  c01 row becomes size 79, split 42 / 8 / 29, ES 67 / 79, 2026-04-29 x10; the c01
  event-id list drops 154 and 160; the representative table shows 154 in a
  singleton c06 and 160 in a singleton c07; "3 rows stand alone" becomes "5 rows".
- **`README.md`:** the reviewer-path line states the archive groups into "5
  descriptive market-story clusters" and "the largest cluster holds 81 rows"; these
  would become 7 clusters and 79 rows.
- **`stats/C01_MARKET_NARRATIVE.md`:** several interlocking figures reference c01 as
  81 rows and would need careful restatement - "81 of the 86 rows" -> 79, the
  outcome counts "42 / 8 / 31" -> 42 / 8 / 29, and "14 of 81" (readout-missing,
  including 153 / 154 / 160) -> 12 of 79 (including 153; 154 and 160 are no longer
  in c01). This is a hand-authored narrative, so its restatement is line-by-line,
  not a regeneration.
- **Likely unchanged:** the reaction matrix, representative-case expansion, and
  event-date-quality distribution exhibits (section 5), and any frontend surface
  outside the effective-evidence constants.

## 7. Live-mutation guidance for L1B-2C

- **Mutate both 154 and 160 together in L1B-2C.** They trigger one coherent
  restatement (5 / 81 -> 7 / 79); splitting them across two live slices would
  restate the same reviewer surfaces twice for no benefit.
- **Neither row needs a ticker or a readout**, and neither should get one - both
  remain legitimately no-ticker no-readout policy/diplomacy stories.
- **Gate note for L1B-2C:** 160's 2026-04-24 is exact-supported; 154's 2026-04-23
  rests on the L1B-2B free-public recheck (OCCRP and Guardian), which is more
  specific than the failed ~2026-04-24. L1B-2C should confirm it is comfortable
  treating 2026-04-23 as the pinned date before the live edit.
- **Exact verification required for L1B-2C:** back up live `events.db`; apply a
  guarded single-field update to exactly rows 154 and 160; confirm only those two
  `event_date` values changed and nothing else; regenerate the K2 exhibit and
  confirm the golden byte-match test passes; update the frontend constants and
  Evidence Overview tests and run the frontend build; restate the README line and
  the C01 narrative figures; confirm the K2 headline reads 86 / 7 / 79; confirm the
  denominators stay 180 / 94 / 86 / 78 / 13; confirm no outcome, readout, or
  anchor-label changed.

## 8. Guardrails and non-claims

- This is a temp-DB proof only; live `events.db` and `price_cache.db` were not
  mutated, and the temp copy was deleted after use.
- A corrected anchor improves date correctness and legibility; it does **not**
  create independent evidence, add a data point, or make any mechanism true.
- The cluster restatement (81 -> 79, 5 -> 7) is a descriptive independence caution,
  not an inferential effective sample size; splitting a mega-cluster into a smaller
  cluster plus singletons neither proves nor disproves any mechanism.
- No p-value, no FDR update, no new pool, no score, no rank. Phase 1 and Phase 2
  pools were neither read nor changed.
- No family-level inference; family lenses are context only.
- Not a trading signal, not a forecast, not a recommendation, and nothing here
  speaks to the future returns of any asset.

## 9. Reproduction note

- **Live `events.db` SHA-256 before and after this task:**
  `d02601183e1d0bd9db18d257332eff8ae06637b972f5031d9a59f3d5eb09b4d8` (size
  50,839,552 bytes, mtime 2026-07-02 12:34) - identical, unchanged.
- **Live `price_cache.db`:**
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (0 bytes) -
  not opened, unchanged.
- **Temp copy:** `<scratchpad>/l1b2c0_tempdb.db`, pristine SHA-256 equal to live
  before mutation; mutated SHA-256
  `b950b22f10e8d660f08b98f61cf6589c5bdbde2b20477982a4453446ac5a7b98`; deleted after
  use. A second short-lived temp copy was used to render the K2 exhibit diff and
  was also deleted. Both temp paths are outside git tracking.
- **Method:** copy live -> temp; assert temp hash == live; run the reports for a
  "before" snapshot; re-hash temp and assert unchanged (reports read-only); apply
  `UPDATE events SET event_date=? WHERE id=? AND event_date='2026-04-29'` for
  154 -> 2026-04-23 and 160 -> 2026-04-24 on the temp copy only; assert exactly rows
  154 and 160 differ and `event_date` is the only changed field; run the reports
  again for an "after" snapshot; diff; render the K2 markdown on the mutated temp
  and diff it against the committed exhibit. The live database was never written.
- **Reports / probes run (all read-only, against the temp copy):**
  `effective_independent_evidence_report.py` (build_report, render_markdown,
  `_assemble_rows`, `build_clusters`), `case_library_reaction_matrix.py`,
  `representative_case_expansion_report.py`, `event_date_quality_distribution_report.py`,
  `event_date_quality_report.py`.
- **Selected rows covered:** 154, 160. Rows 46 and 153 were not included;
  duplicate-collapse rows 42 and 49 were not included; ticker-attribution row 9 was
  not included.
- No provider or market-data API call, no `/analyze`, no fetch or backfill, and no
  live DB or cache mutation was performed.
