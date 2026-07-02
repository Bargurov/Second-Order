# L1B-2B exact-date gate - halted before mutation (no live repair)

**Status:** read-only gate record. L1B-2B was stopped at the exact-date gate
*before* any database change. No row was edited, `events.db` was opened read-only,
and no reviewer surface (K2 exhibit, frontend, README, C01 narrative) was
restated. This note records why the slice was deferred and what the next task must
do.

## 1. What a reviewer should take away first

- **L1B-2B was halted before mutation.** The plan was to move rows 154 and 160
  from 2026-04-29 to a shared 2026-04-24 and restate the K2 cluster headline. It
  did not happen: the source support for row 154 did not meet the exact-date gate,
  and the only gate-permitted single move (160 alone) does not produce the
  intended restatement.
- **Nothing changed.** Live `events.db` stayed at
  `d02601183e1d0bd9db18d257332eff8ae06637b972f5031d9a59f3d5eb09b4d8`,
  `price_cache.db` stayed unchanged, and no frontend / README / K2 / C01 artifact
  was restated. The K2 headline remains 86 accepted rows / 5 clusters / largest
  cluster 81.
- **The next unit of work is a revised temp-DB proof** for the corrected source
  picture (154 -> 2026-04-23, 160 -> 2026-04-24), evaluated on a temporary copy
  before any live mutation.

## 2. Exact-date gate result

The gate requires an exact, source-pinned event date before a live date change.

- **Row 160 - PASSES.** The France 24 story this row mirrors is dated
  **2026-04-24** (Araghchi's initial Islamabad arrival), with a dated source URL.
  The L1B-0 decision recorded an exact 2026-04-24 (no approximation marker).
- **Row 154 - FAILS.** L1B-0 recorded only an approximate **~2026-04-24** for the
  UK / Kyrgyzstan sanctions-letter story (the approximation marker appears in the
  L1B-0 ledger's mutation column, the row-by-row decision, and its missing-readout
  section; the source was cited indirectly, without a dated primary URL). An
  approximate date does not satisfy the gate, so row 154 must not be moved to a
  specific 2026-04-24.

## 3. Source recheck

A free-public source recheck of row 154 (the UK / Kyrgyzstan sanctions-letter
story) points **away** from 2026-04-24 rather than confirming it:

- The matching OCCRP coverage appears dated **2026-04-23**.
- The matching Guardian coverage also appears dated **2026-04-23**.

So the recheck strengthens the halt: not only was 2026-04-24 approximate for row
154, the better-supported date now looks like **2026-04-23**. Moving 154 and 160
to a *shared* 2026-04-24 two-row cluster is therefore not source-supported. No
paid API, market-data provider, `/analyze`, fetch, or backfill was used.

## 4. Why 160-only was rejected

Moving only row 160 (the one row that passes the gate) was considered and
rejected. On a read-only temporary copy of the current live database, a 160-only
move produces an intermediate K2 state that is **not** the intended L1B-2B
restatement:

| scenario | clusters | largest cluster | 154 | 160 |
|---|---|---|---|---|
| current live | 5 | 81 | in c01 | in c01 |
| intended L1B-2B (both move) | 6 | 79 | new 2-row cluster | new 2-row cluster |
| 160-only (gate-permitted) | 6 | **80** | stays in c01 | **singleton** at 2026-04-24 |

The intended 6-cluster / largest-79 / new two-row cluster is only reachable if
both rows move to the same date. With 160 alone, the largest cluster is 80 and 160
becomes a one-row cluster (the archive row already at 2026-04-24, id 119, is a
synthetic seed excluded from the accepted-corpus lens, so it does not absorb it).
A 160-only move would restate the reviewer surfaces to 6 / 80 now and then require
a second restatement later, which is avoidable churn. It was not done.

## 5. State after the halt (nothing restated)

- **No DB mutation occurred.** Rows 154 and 160 remain at 2026-04-29.
- **No frontend restatement.** `frontend/src/lib/effective-independent-evidence.ts`
  still carries 86 / 5 / 81, which is correct for the unchanged database.
- **No README, K2 exhibit, or C01 narrative restatement.** These continue to
  describe the current, unchanged K2 state.
- Denominators are untouched: archive 180, accepted coverage 94, accepted
  track-record 86, event-study available 78 / 94, staged candidates 13.
- The historical L1 records (`L1_ANCHOR_REPAIR_BATCH.md`, `L1B_REPAIR_PREVIEW.md`,
  `L1B1_TEMP_DB_PROOF.md`, `L1B2A_LIVE_REPAIR.md`) are unchanged; they remain
  records of what was known at their time.

## 6. Next required task

A revised temp-DB proof for the corrected source situation, on a temporary copy
only, before any live mutation:

- test row 154 -> **2026-04-23** (the recheck-supported date), no ticker;
- test row 160 -> **2026-04-24** (gate-passed), no ticker;
- recompute the K2 cluster structure and confirm the exact new headline, the new
  cluster membership of 154 and 160, and whether they now share a date or land
  separately;
- confirm the reaction-matrix, representative-case, and event-date-quality report
  impact, and the frontend / README / C01 restatement needed;
- only after that proof, decide the live L1B-2C slice and its restatement.

Note that if 154 belongs to 2026-04-23 and 160 to 2026-04-24, the two rows no
longer share a date, so the "shared two-row 2026-04-24 cluster" assumption from
the L1B-1 temp proof no longer holds and must be re-derived, not carried over.

## 7. Guardrails and non-claims

- This is a read-only gate record; it repairs nothing and changes no reviewer
  surface.
- Deferring a date correction improves honesty: an approximate or contradicted
  date is not pinned to a specific day without support.
- Cluster counts are descriptive independence cautions, not an inferential
  effective sample size.
- No p-value, no FDR update, no new pool, no score, no rank.
- No family-level inference.
- Not a trading signal, not a forecast, not a recommendation, and nothing here
  speaks to the future returns of any asset.

## 8. Reproduction note

- `events.db` opened read-only; SHA-256
  `d02601183e1d0bd9db18d257332eff8ae06637b972f5031d9a59f3d5eb09b4d8` verified
  unchanged before and after. `price_cache.db`
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (0 bytes)
  unchanged.
- The 160-only / both-move comparison in section 4 was computed on a temporary
  copy of `events.db` (outside git), deleted after use, via
  `scripts/effective_independent_evidence_report.py` internals
  (`_assemble_rows`, `build_clusters`); the live database was not mutated.
- Source basis: L1B-0 (`stats/L1B_REPAIR_PREVIEW.md`) plus the free-public recheck
  in section 3. No provider or market-data API call, no `/analyze`, no fetch or
  backfill.
