# L1B-2A live anchor repair - first safe slice (7 / 29 / 39 / 239)

**Status:** live `events.db` mutation, applied and verified. This slice corrected
one anchor date (row 239) in the live archive and confirmed three already-correct
anchors (rows 7, 29, 39). It was taken only after a full temp-DB proof (L1B-1) and
a timestamped backup. `price_cache.db` was not touched. The rows that L1B-1 showed
would move the K2 cluster structure (154, 160) were deliberately held back.

## 1. What a reviewer should take away first

- **The live repair was limited to rows 7, 29, 39 and 239.** The only field
  written to the database was `events.event_date` on row 239.
- **Rows 154 and 160 are intentionally deferred.** L1B-1 showed that correcting
  them moves the K2 cluster count 5 -> 6 and the largest cluster 81 -> 79; that
  restatement is a separate later slice. Duplicate-collapse, ticker-attribution
  and out-of-window rows are likewise deferred.
- **Row 239 was corrected from 2026-05-01 to 2026-04-29** (the FOMC meeting day;
  the stored date lagged the decision by two sessions).
- **This changed row 239's reaction-matrix readout but nothing structural.** The
  SPY-relative abnormal-return readout for 239 recomputed (1d -2.03 -> -0.20,
  5d -6.38 -> -1.41, 20d -8.89 -> -10.04); the outcome stayed `unresolved`, the K2
  headline stayed 86 accepted rows / 5 clusters / largest 81, and every
  denominator stayed unchanged.

## 2. Live mutation scope

- **Included rows:** 7, 29, 39 (confirm-only) and 239 (date correction).
- **Excluded rows:** 154, 160 (K2-restatement slice, deferred), and 2, 9, 30, 38,
  42, 46, 49, 153 (duplicate / ticker-attribution / out-of-window / human-source
  rows, deferred to later policy slices).
- **Exact DB field changed:** `events.event_date` on `id = 239`,
  `2026-05-01` -> `2026-04-29`. Exactly one row, one column. A guarded
  `UPDATE ... WHERE id=239 AND event_date='2026-05-01'` inside `BEGIN IMMEDIATE`
  reported `rowcount = 1`; a full-table before/after comparison against the backup
  confirmed row 239 was the only row that changed and `event_date` the only field.
- **Provenance / correction records added:** none in the database.
- **Why no in-DB provenance record was added:** the two candidate tables do not
  cleanly host a post-hoc anchor-date correction, and forcing one in would
  misrepresent their meaning.
  - `event_provenance` is an *intake*-provenance table (its NOT-NULL columns are
    `source_type`, `mechanism_label_provenance`, `intake_path`, `created_at`) and
    is written only by the curated / candidate intake scripts
    (`curated_event_intake_apply.py`, `z1b_candidate_pack_copy_ingest.py`). None
    of these four rows has a record there; an `intake_path` value for a July-2026
    date fix would be untrue.
  - `event_hygiene` is a corpus-status override table (`override_class` values such
    as `synthetic_seed`); a date correction is not a corpus-membership override.
  - `events.notes` is free text but is read by no report; writing it would add
    mutation surface for no consumer.
  - The explicit before/after correction record therefore lives in this committed
    note (old date, new date, source, reason). The anchor was not silently
    re-dated: this artifact is the durable correction entry required by the L1A
    repair protocol.
- **Rows 7, 29, 39:** `event_date` was already correct (2026-04-05) and was not
  changed. Their source confirmation is recorded here rather than in the database,
  because there is no clean existing provenance field for confirming a
  news-intake row's date, and the task forbids inventing schema. Their database
  rows are byte-for-byte unchanged.

## 3. Source basis

The source ledger is L1B-0 (`stats/L1B_REPAIR_PREVIEW.md`) and the L1B-1 temp-DB
proof (`stats/L1B1_TEMP_DB_PROOF.md`); no new browsing was required.

- **7 / 29** - Al Jazeera coverage dated 2026-04-05 (Trump / Hormuz threat and the
  Strait-closure ultimatum). Stored date already 2026-04-05: confirmed.
- **39** - opec.org: the OPEC+ Eight met on 2026-04-05. Stored date already
  2026-04-05: confirmed.
- **239** - federalreserve.gov statement `monetary20260429a.htm` and CNBC of
  2026-04-29: the FOMC hold and the Powell statement were the 2026-04-29 meeting;
  the stored 2026-05-01 lagged by two sessions. (The curated event 293 already
  carries this exact Fed URL in `event_provenance` with the correct 2026-04-29
  date, which corroborates the anchor and confirms the provenance table's
  intake-only role.)

No paid API, no market-data provider, no `/analyze`, no fetch or backfill was used.

## 4. Before / after table

Readouts are the primary ticker's SPY-relative abnormal return (AR%) at 1d / 5d /
20d, as carried in the case-library reaction matrix. "n/a (not a case)" means the
row is not one of the 15 representative reaction-matrix cases.

| id | old event_date | new event_date | old source state | new source state | old reaction readout (1d/5d/20d) | new reaction readout | outcome (before -> after) | cluster (before -> after) | denominator impact |
|---|---|---|---|---|---|---|---|---|---|
| 7 | 2026-04-05 | 2026-04-05 (unchanged) | no provenance record | confirmed in this note | +0.25 / -7.50 / -10.56 (XLE) | unchanged | support -> support | c01 -> c01 | none |
| 29 | 2026-04-05 | 2026-04-05 (unchanged) | no provenance record | confirmed in this note | +0.25 / -7.50 / -10.56 (XLE) | unchanged | contradiction -> contradiction | c01 -> c01 | none |
| 39 | 2026-04-05 | 2026-04-05 (unchanged) | no provenance record | confirmed in this note | n/a (not a case) | n/a | contradiction -> contradiction | c01 -> c01 | none |
| 239 | 2026-05-01 | 2026-04-29 | no provenance record | correction recorded in this note | -2.03 / -6.38 / -8.89 (BAC) | -0.20 / -1.41 / -10.04 (BAC) | unresolved -> unresolved | c01 -> c01 | none |

Row 239 stayed inside cluster c01 (it moved from 2026-05-01 into the existing
2026-04-29 c01 cohort); its cluster membership and the cluster's size (81) did not
change.

## 5. Affected report restatement

Report generators were re-run against the mutated live DB. Only artifacts whose
generated content actually changed were updated.

- **`stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md` (K2) - UPDATED (2 lines).** The
  2026-04-29 shared-date count moved from 11 to 12 (row 239 joined that cohort)
  in the "top clustered dates" summary and in the c01 "why grouped" cell. This
  file is byte-match golden-tested; it now matches the current render exactly. The
  K2 headline is unchanged: **86 accepted rows, 5 clusters, largest cluster 81.**
- **`stats/CASE_LIBRARY_REACTION_MATRIX.md` - UPDATED (1 row).** Row 239's AR
  readout was refreshed to the recomputed values (1d -0.20, 5d -1.41, 20d -10.04)
  taken from the generator's `--json` output; the outcome column stays
  `unresolved` and the anchor-quality column stays `manual_review_needed`. This
  file is a hand-maintained markdown exhibit whose AR table is transcribed from
  the generator, so the single stale row was corrected in place rather than
  regenerating (which would discard the reviewer narrative).
- **`stats/REPRESENTATIVE_CASE_EXPANSION.md` - UNCHANGED.** Row 239's displayed
  fields (role, family, outcome `unresolved`, event-study available, anchor label
  `manual_review_needed`) do not depend on the specific date value; the file shows
  no event date or AR for the row.
- **`stats/EVENT_DATE_QUALITY_DISTRIBUTION.md` - UNCHANGED.** Row 239's anchor
  label stayed `manual_review_needed` (the classifier keys on headline wording,
  not the date value); the distribution histogram is identical.

**Exact 239 reaction-matrix AR change:** 1d -2.03 -> -0.20, 5d -6.38 -> -1.41,
20d -8.89 -> -10.04. Outcome `unresolved`, unchanged.

**K2 headline after mutation:** 86 / 5 / 81 (accepted rows / clusters / largest).

**Denominators after mutation:** archive 180, accepted coverage 94, accepted
track-record 86, event-study available 78 / 94, staged candidates 13 - all
unchanged.

**Tests:** the four report test modules ran green (141 tests, including the K2
committed-markdown byte-match golden test).

**Frontend:** `frontend/src/lib/effective-independent-evidence.ts` hardcodes
86 / 5 / 81; those values are unchanged by this slice, so no frontend edit was
made.

## 6. Verification

- **events.db SHA-256 before:**
  `ae3a1187c4c70ae62d29d9dd087bcdd9ec98a8f8fa454136ad891cf8408d23ba`
  (50,839,552 bytes, mtime 2026-06-09 23:12).
- **events.db SHA-256 after:**
  `d02601183e1d0bd9db18d257332eff8ae06637b972f5031d9a59f3d5eb09b4d8`.
- **Backup:** `<scratchpad>/events.db.backup.20260702T123458`, SHA-256
  `ae3a1187c4c70ae62d29d9dd087bcdd9ec98a8f8fa454136ad891cf8408d23ba` (equal to the
  pre-mutation live hash). The backup lives outside git tracking.
- **price_cache.db before and after:**
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
  (0 bytes) - unchanged.
- **Row-level mutation check:** a full-table before/after comparison against the
  backup returned exactly `[239]`; within row 239 the only differing field was
  `event_date` (`2026-05-01` -> `2026-04-29`).
- **Unselected-row no-change check:** no other event row changed; rows 154 and 160
  and the eight deferred rows are byte-for-byte unchanged.
- **Report checks:** K2, reaction matrix, representative-case expansion and
  event-date-quality distribution were re-run against the live DB; the two
  updated markdown artifacts match their regenerated content.
- **cp1252 / Windows-safe:** the changed markdown files are ASCII-only.
- **Banned-framing grep:** the changed markdown carries no trading-signal,
  forecast, recommendation or significance framing except in negated non-claims.
- **git diff --check:** clean.
- **DB files staged:** none. `events.db`, `price_cache.db` and the backup are
  git-ignored and were not staged.

## 7. Guardrails and non-claims

- Anchor repair improves the archive's date correctness and legibility; it does
  **not** create independent evidence, add a data point, or make any mechanism
  true.
- A moved readout (row 239) is a correctness side-effect of anchoring the reaction
  window to the true event date; it is not an attempt to change an outcome, and
  the outcome label did not change.
- No p-value, no FDR update, no new pool, no score, no rank. Phase 1 and Phase 2
  pools were neither read nor changed.
- No family-level inference; family lenses are context only.
- This is not a trading signal, not a forecast, not a recommendation, and says
  nothing about the future returns of any asset.

## 8. Reproduction note

- **Backup + mutation:** `events.db` copied to
  `<scratchpad>/events.db.backup.20260702T123458` (hash verified equal to live),
  then a single guarded statement applied inside a transaction:
  `UPDATE events SET event_date='2026-04-29' WHERE id=239 AND event_date='2026-05-01'`
  (`rowcount = 1`, committed). Row-level and price_cache checks followed.
- **Affected report commands (read-only, against the live DB):**
  - `python scripts/effective_independent_evidence_report.py --db-path events.db`
  - `python scripts/case_library_reaction_matrix.py --db-path events.db --json`
  - `python scripts/representative_case_expansion_report.py --db-path events.db`
  - `python scripts/event_date_quality_distribution_report.py --db-path events.db`
- **Tests:** `python -m unittest tests.test_effective_independent_evidence_report
  tests.test_case_library_reaction_matrix
  tests.test_representative_case_expansion_report
  tests.test_event_date_quality_distribution_report` (141 tests, OK).
- No provider or market-data API call, no `/analyze`, no fetch or backfill, and no
  `price_cache.db` mutation was performed.
