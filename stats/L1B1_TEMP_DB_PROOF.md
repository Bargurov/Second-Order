# L1B-1 temp-DB proof - first anchor mutations (temp copy only)

**Status:** temp-DB proof, not a live repair. Live `events.db` and
`price_cache.db` were never mutated. A byte-identical copy of `events.db` was
made outside git, the three in-window date corrections were applied to that copy
only, and the affected reports were re-run against the copy to show exactly what
a later live L1B-2 task would move. Nothing in the tracked archive was changed by
this task except this note.

## 1. What a reviewer should take away first

- **This is a temp-DB proof, not the live repair.** It demonstrates, on a
  throwaway copy, what the first anchor mutations would change; it repairs
  nothing in `events.db`. The demonstrative sense of "proof" here means a
  worked before/after showing; it is not a claim that any mechanism is confirmed.
- **Six rows were tested: 7, 29, 39 (confirm-only) and 154, 160, 239
  (date corrections).** Only the three date corrections actually mutate the copy;
  7, 29 and 39 keep their stored `event_date` unchanged, so they are no-ops on the
  events table and their populated readouts stay valid.
- **The slice is safe to mutate live, but not blast-radius-free.** No denominator
  moves and no outcome label flips for any of the six. Two downstream restatements
  are required and are the whole point of proving first: (a) correcting 154 and 160
  to 2026-04-24 pulls them out of the 81-row c01 mega-cluster into a new 2-row
  cluster, moving the K2 cluster count 5 -> 6 and the largest-cluster size 81 -> 79;
  (b) correcting 239 to 2026-04-29 recomputes its SPY-relative reaction-matrix
  readout at every horizon (outcome stays `unresolved`). Neither is a defect; both
  are correctness side-effects that a live L1B-2 must restate explicitly instead of
  leaving stale numbers standing.

## 2. Mutation scope

Included in this proof (the six listed rows only):

| id | class | temp action |
|---|---|---|
| 7 | source-confirmed | confirm date 2026-04-05; no `event_date` change |
| 29 | source-confirmed | confirm date 2026-04-05; no `event_date` change |
| 39 | source-confirmed | confirm date 2026-04-05; no `event_date` change |
| 154 | source-contradicts-date | correct `event_date` 2026-04-29 -> 2026-04-24; stays no-ticker |
| 160 | source-contradicts-date | correct `event_date` 2026-04-29 -> 2026-04-24; stays no-ticker |
| 239 | source-contradicts-date | correct `event_date` 2026-05-01 -> 2026-04-29 (FOMC day) |

Explicitly deferred to later slices (not touched here):

- **2, 49** - Artemis duplicate/collapse pair; needs duplicate policy first.
- **30, 42** - fighter-jet cross-date duplicate with opposite outcome labels;
  needs duplicate policy and carries readout/outcome-bookkeeping consequences.
- **9** - ticker-attribution-noise row (DRIV); needs attribution policy, not a
  date edit.
- **38** - source-insufficient marking, not a date edit.
- **46** - date correction exits the c01 window (2026-03-26); high-consequence,
  needs explicit cluster/denominator restatement first.
- **153** - needs a human sourcing decision; no mutation until resolved.

Reason for the limit: this slice takes only source-confirmed confirmations and
in-window, no-ticker or calendar-confirmable date corrections, so the blast radius
is knowable in advance. Duplicate-collapse, ticker-attribution, and
window-exiting rows are held for later slices where their bookkeeping is handled
deliberately.

## 3. Before / after and mutation-preview table

Cluster ids are from the K2 clustering re-run against the temp copy. "c01(81)"
means row sat in cluster c01 which held 81 rows before the edits; "c01(79)" is the
same c01 after two rows left it. Anchor-quality labels are the live
`event_date_quality` classifications (wording-based), re-run on the temp copy.

| id | cur date | proposed date | cur label | proposed label | cur ticker/asset | ticker change | cur readout avail | expected readout impact | expected cluster impact | expected denom impact | source basis (L1B-0) | safe for L1B-2? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7 | 2026-04-05 | 2026-04-05 (confirm) | manual_review_needed | manual_review_needed (unchanged) | XLE (+LMT/RTX/DAL/UAL/JETS) | none | available | none - date unchanged, readouts intact | none - stays c01 | none | Al Jazeera Apr 5 (Hormuz/"hell" threat) | yes |
| 29 | 2026-04-05 | 2026-04-05 (confirm) | duplicate_or_deferred | duplicate_or_deferred (unchanged) | XLE (+XOP/CVX/JETS/DAL/UAL) | none | available | none - date unchanged | none - stays c01 | none | Al Jazeera Apr 5 (Hormuz closure threat) | yes |
| 39 | 2026-04-05 | 2026-04-05 (confirm) | manual_review_needed | manual_review_needed (unchanged) | XLE (+OXY/SLB/AAL/DAL/DOW) | none | available | none - date unchanged | none - stays c01 | none | opec.org (OPEC+ Apr 5 meeting) | yes |
| 154 | 2026-04-29 | 2026-04-24 | manual_review_needed | manual_review_needed (unchanged) | none | none (stays no-ticker) | unavailable (no ticker) | none - no ticker, no readout | leaves c01 -> new 2-row cluster at 2026-04-24 | none | OCCRP/France 24 Apr 24 (Kyrgyzstan sanctions letter) | conditional |
| 160 | 2026-04-29 | 2026-04-24 | partial_anticipation | partial_anticipation (unchanged) | none | none (stays no-ticker) | unavailable (no ticker) | none - no ticker, no readout | leaves c01 -> same new 2-row cluster | none | France 24 Apr 24 (Araghchi arrives Pakistan) | conditional |
| 239 | 2026-05-01 | 2026-04-29 | manual_review_needed | manual_review_needed (unchanged) | BAC (+KRE/IYR/TLT) | none | available (SPY-relative readout) | recomputes: 1d AR -2.03->-0.20, 5d AR -6.38->-1.41, 20d AR -8.89->-10.04; outcome stays unresolved | none - stays c01 (joins Apr-29 cohort) | none | federalreserve.gov / CNBC Apr 29 (FOMC hold) | conditional |

Outcome labels observed unchanged across all six in the before/after run:
7 support, 29 contradiction, 39 contradiction, 154/160/239 unresolved. No
confirmation silently turned into a new outcome claim.

## 4. Source basis

The source ledger for these six rows is `stats/L1B_REPAIR_PREVIEW.md` (L1B-0),
which was consulted as-is; no new browsing was required because L1B-0 is
unambiguous for all six. In brief, per that ledger:

- **7 / 29** - Al Jazeera coverage dated 2026-04-05 (Trump/Hormuz "hell" threat
  and the Strait-closure ultimatum). Stored date already 2026-04-05: confirm.
- **39** - opec.org: the OPEC+ Eight met on 2026-04-05. Stored date already
  2026-04-05: confirm.
- **154** - OCCRP / France 24: the cross-party UK letter urging sanctions on
  Kyrgyz officials is a 2026-04-24 story; stored 2026-04-29 lags by ~5 days.
- **160** - France 24: Araghchi's Islamabad arrival was 2026-04-24; stored
  2026-04-29 lags by ~5 days.
- **239** - federalreserve.gov statement `monetary20260429a.htm` and CNBC Apr 29:
  the FOMC hold and Powell statement were the 2026-04-29 meeting; stored
  2026-05-01 lags by two days.

The full URL list is in L1B-0 section 10. This note does not re-quote the
articles. L1B-0's two out-of-scope mechanism-text notes (row 39 "extending" vs
"resuming unwinding"; row 239 stored "5.25-5.50%" vs sourced "3.50-3.75%") are
logged there as separate mechanism-text tasks and are not anchor edits.

## 5. Temp-DB impact summary

Five affected reports were run against the temp copy before and after the three
date corrections (all read-only, via each script's own `--db-path` flag):

| report | script | before vs after | what moved |
|---|---|---|---|
| Event-date-quality distribution | `event_date_quality_distribution_report.py` | UNCHANGED | histogram identical; no quality label moved |
| Selected-row anchor labels | `event_date_quality_report.py` | CHANGED (echo only) | only the echoed `event_date` for 154/160/239; every quality label unchanged |
| K2 effective independent evidence | `effective_independent_evidence_report.py` | CHANGED | cluster_count 5 -> 6, multi_row_clusters 2 -> 3, largest_cluster_size 81 -> 79; new 2-row cluster at 2026-04-24 (154 + 160); denominators unchanged |
| Case-library reaction matrix | `case_library_reaction_matrix.py` | CHANGED | echoed `event_date` for 154/160/239, plus row 239's SPY-relative AR/CAR/SAR readout recomputed at 1d/5d/20d; 154/160 readouts stay unavailable; outcomes unchanged |
| Representative case expansion | `representative_case_expansion_report.py` | CHANGED (echo only) | only the echoed `event_date` for 154/160/239; `event_study_available` and outcome unchanged |

**What changed.**
- **K2 cluster structure moves for 154 and 160.** No-ticker rows join a cluster
  only by an exact shared event date; at 2026-04-29 they were absorbed into the
  Apr-29 c01 cohort, and at 2026-04-24 they share a date only with each other, so
  they form a new 2-row cluster. This shifts the two headline K2 numbers
  (5 -> 6 clusters, 81 -> 79 largest).
- **Row 239's abnormal-return readout recomputes.** The event study reads a
  `price_cache` table inside `events.db` (51,687 rows), so moving the anchor two
  sessions earlier re-anchors the window and changes the SPY-relative AR/CAR/SAR.
  The stored per-ticker return fields for 239 are null; the moving numbers are the
  event-study readout, and the case stays `unresolved`.

**What did not change.**
- **Denominators / funnel:** archive 180, accepted-coverage 94, accepted
  track-record 86, event-study-available 78, staged 13 - identical before and
  after. No row was added, removed, or reclassified, so no denominator restatement
  is required.
- **Outcome labels:** all six unchanged.
- **Anchor-quality labels:** all six unchanged (the classifier keys on headline
  wording and duplicate/thread structure, not the specific date value).
- **The confirm-only rows (7, 29, 39):** no `event_date` change, so no readout,
  cluster, or label movement attributable to them.

**Restatement required?** No denominator restatement. A K2 cluster restatement is
required if 154/160 are corrected live (cluster count and largest-cluster size
move), and a reaction-matrix readout re-run is required if 239 is corrected live.
Both restatements are downstream regeneration, not evidence changes.

## 6. Live-mutation guidance for L1B-2

- **Safe now, no downstream restatement - 7, 29, 39.** These are confirmations:
  `event_date` does not change. The only associated live action is recording the
  source citation, which belongs in the existing `event_provenance` table
  (`source_url`, `source_published_at`, `source_publisher`) - a separate axis from
  the events table, not exercised in this proof. There is a clean schema home for
  anchor-source notes, so there is no schema limitation to report.
- **Safe with a reaction-matrix re-run - 239.** In-window correction
  (2026-05-01 -> 2026-04-29); the row stays in c01 and its outcome stays
  `unresolved`, but its SPY-relative readout recomputes. L1B-2 must re-run the
  reaction matrix and refresh any exhibit or frontend surface that shows 239's AR,
  so no stale (May-1-anchored) readout is left standing. Conditional on that
  regeneration.
- **Conditional, requires K2 + frontend restatement - 154, 160.** In-window
  correction (2026-04-29 -> 2026-04-24) with no ticker, readout, outcome, or
  denominator change, but the two rows leave c01 and form a new 2-row cluster,
  moving the K2 cluster count (5 -> 6) and largest-cluster size (81 -> 79). L1B-2
  must regenerate the K2 exhibit and the frontend effective-evidence card with an
  explicit restatement note.
- **Defer - none of these six.** (The rows deferred to later slices are the other
  eight: 2, 9, 30, 38, 42, 46, 49, 153, listed in section 2.)

**Exact verification needed for L1B-2 (live):**
1. Record before/after `event_date` for each corrected row as an explicit
   correction entry (no silent redating), per the L1A repair protocol.
2. Re-run and compare: event-date-quality distribution (expect unchanged), the K2
   report and regenerate its exhibit (expect cluster_count 5 -> 6, largest
   81 -> 79, a new 2026-04-24 pair), the reaction matrix (expect 239's AR
   recompute), and the representative-case reports (expect date echo only).
3. Refresh the frontend effective-evidence card if the K2 numbers ship there.
4. Confirm the funnel stays 180 / 94 / 86 / 78 / 13 and that no outcome label
   flips.
5. Add source citations for 7 / 29 / 39 (and the corrected dates' sources for
   154 / 160 / 239) via `event_provenance`, not by forcing a new events-table
   field.
6. Re-verify live `events.db` hash before and after each mutation and keep the
   before/after row snapshots.

## 7. Guardrails and non-claims

- This is a temp-DB proof only. Live `events.db` and `price_cache.db` were not
  mutated; the mutations were applied to a throwaway copy outside git and the copy
  was deleted after use.
- Repaired or confirmed anchors do **not** create independent evidence. A more
  accurate date improves legibility and trust; it does not add a data point or
  make any mechanism true.
- No p-value, no FDR update, no new pool, no score, no rank. Phase 1 and Phase 2
  pools were neither read nor changed.
- A moved readout (row 239) is a correctness side-effect of anchoring the window
  to the true date; it is not an attempt to change an outcome, and the outcome
  label did not change.
- A cluster moving (154 / 160) is a descriptive independence caution, not an
  inferential sample size; it neither proves nor disproves any mechanism.
- This is not a trading signal, not a forecast, not a recommendation, and says
  nothing about the future returns of any asset.

## 8. Reproduction note

- **Live `events.db` SHA-256 before and after this task:**
  `ae3a1187c4c70ae62d29d9dd087bcdd9ec98a8f8fa454136ad891cf8408d23ba`
  (size 50,839,552 bytes, mtime 2026-06-09 23:12) - identical, unchanged.
- **Live `price_cache.db`:**
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
  (size 0 bytes, mtime 2026-04-11 21:20) - not opened, unchanged. (The event
  study reads the `price_cache` table inside `events.db`, not this empty file.)
- **Temp copy:** `<scratchpad>/l1b1_tempdb.db`, pristine SHA-256 equal to live
  before mutation; mutated SHA-256
  `1d144e0db4800ca790b3668e69564675a0ab7a26fd23c7d352488443f68ad992`; deleted
  after use. The temp path is outside git tracking.
- **Method:** copy live -> temp; assert temp hash == live hash; run the five
  reports for a "before" snapshot; re-hash temp and assert it is unchanged
  (reports are read-only against `--db-path`); apply `UPDATE events SET
  event_date=? WHERE id=?` for 154 -> 2026-04-24, 160 -> 2026-04-24,
  239 -> 2026-04-29 on the temp copy only; assert exactly rows 154, 160, 239
  differ from live and no other row changed; run the five reports again for an
  "after" snapshot; diff. A scratchpad-only helper carried a hard guard refusing
  to run if the target path resolves to `events.db`; it was kept uncommitted.
- **Reports / probes run (all read-only, `--db-path` against the temp copy):**
  `event_date_quality_distribution_report.py`, `event_date_quality_report.py`,
  `effective_independent_evidence_report.py`, `case_library_reaction_matrix.py`,
  `representative_case_expansion_report.py`, plus a direct read-only
  `build_clusters` call for complete per-row cluster membership.
- **Selected rows covered:** 7, 29, 39, 154, 160, 239. Rows 46 and 153 were not
  included; duplicate-collapse rows 42 and 49 were not included; ticker-attribution
  row 9 was not included.
- No provider or market-data API call, no `/analyze`, no fetch or backfill, and no
  live DB or cache mutation was performed.
