# L1B closeout - anchor-repair phase complete, handoff to L2

**Status:** closeout / documentation note. It records what the L1B anchor-repair
phase did, what changed in the current research surfaces, what did not change,
what remains deferred, and why the next phase is L2 annotation / source-pinning
rather than more date repair. It mutates nothing: `events.db` and `price_cache.db`
were opened read-only and are unchanged; no row was collapsed, excluded, relabeled,
or deleted, and no L2 policy was implemented.

## 1. What L1B accomplished

- **L1B was an anchor-repair and current-state restatement phase.** Its purpose was
  archive date correctness and legibility, not new results.
- It **did not create new evidence**, **did not change event-study math**, and
  **did not change any outcome label** to improve how the archive reads.
- It repaired **three live event dates** (each source-pinned, backed up, and applied
  as a single guarded field write, with the before/after recorded in the committed
  slice notes):
  - row **239**: 2026-05-01 -> **2026-04-29** (FOMC meeting day; L1B-2A)
  - row **154**: 2026-04-29 -> **2026-04-23** (UK/Kyrgyzstan sanctions letter; L1B-2C)
  - row **160**: 2026-04-29 -> **2026-04-24** (Araghchi Islamabad arrival; L1B-2C)

## 2. What changed in the current research surfaces

The three date repairs and their restatements moved the following current-state
numbers (all reconfirmed by a fresh read-only recompute for this closeout):

- **K2 market-story clusters:** 86 / 5 / 81 -> **86 / 7 / 79** (rows 154 and 160 left
  c01 to become separate singletons c06 @ 2026-04-23 and c07 @ 2026-04-24).
- **c01 (largest cluster):** size 81 -> **79**; outcome split 42 / 8 / 31 ->
  **42 / 8 / 29** (the two departing rows are both `unresolved`, so support and
  contradiction are unchanged).
- **Representative cases in the largest cluster:** 14 / 15 -> **12 / 15** (154 and
  160 now sit in singletons; the 15-case total is unchanged).
- **Distinct accepted event dates:** 17 -> **19** (2026-04-23 and 2026-04-24 became
  new distinct dates).
- **Global independent-window capacity:** 1d 17 -> **19**, 5d 6 -> **7**, 20d stays
  **3**.
- **Row 239 reaction-matrix / readout restatement:** re-anchoring the window two
  sessions earlier recomputed the SPY-relative readout - 1d -2.03 -> **-0.20**,
  5d -6.38 -> **-1.41**, 20d -8.89 -> **-10.04** (SAR/CAR restated to match); outcome
  stayed `unresolved`. The current EXPANDED_CASE_NOTES dossier carries these values.
- **Sanction and ceasefire family-span restatements:** sanction 2026-04-29..04-29
  (1 distinct date) -> **2026-04-23 .. 2026-04-29** (2 distinct dates); ceasefire
  2026-04-08..04-29 -> **2026-04-08 .. 2026-04-24** (3 distinct dates, unchanged).
- **Row 239 monetary endpoint cleanup:** the `monetary_policy_or_rates` family span
  endpoint was restated 2026-05-01 -> **2026-04-30** (row 231 is the current max
  after 239 left 05-01), and the 239 dossier date was cleaned 2026-05-01 ->
  **2026-04-29**.

## 3. What did not change

- **Denominators (funnel):** archive **180**, accepted coverage **94**, accepted
  track-record **86**, event-study available **78 / 94**, staged candidates **13** -
  all unchanged; no row was added, removed, or reclassified.
- **No outcome labels changed.**
- **No tickers added to 154 / 160** (both remain legitimately no-ticker
  policy/diplomacy rows).
- **No readout availability changed for 154 / 160** (both remain no-readout; the
  missing readout reflects no assigned market asset, not an unknowable anchor).
- **No p-value, no FDR update**, no new pool, no score, no rank; the closed Phase 1
  and Phase 2 pools were neither read nor changed.
- **No event-study math change** (a moved readout is a correctness side-effect of a
  corrected date, not a recomputed method).
- **No family-level inference.**
- **No trading signal / forecast / recommendation / alpha** was introduced anywhere.

## 4. Rows confirmed but not live-mutated

Rows **7, 29, 39** were source-confirmed (Al Jazeera 2026-04-05 for 7/29; opec.org
2026-04-05 for 39) but their stored `event_date` was already correct, so the
completed live slices wrote no date field for them. Their database rows are
byte-for-byte unchanged; the source confirmation is recorded in the L1B-2A slice
note rather than forced into a schema field that does not fit a post-hoc anchor
confirmation.

## 5. Deferred L1 candidates

These rows were selected in L1A but deliberately not resolved live in L1B; each is
grounded in the L1A batch, the L1B-0 preview, and the L2 inventory. No closure is
claimed for any of them.

- **Duplicate / cross-date same-story policy (L2 inventory groups G1-G9):**
  30 / 42; 2 / 49; 39 / 53 / 54 / 64 / 70; 40 / 44; 25 / 50; 43 / 60; 16 / 72;
  26 / 48 / 61. These are one story re-saved across ingestion dates; three groups
  (30/42, the OPEC saga, 26/48/61) carry an outcome conflict.
- **Ticker-attribution noise:** 9 / 51 (DRIV on a UK local-crime item). The Artemis
  pair 2 / 49 (default LMT/DRIV) also carries an attribution facet but is filed
  under the duplicate policy above; 46 carries a DRIV attribution facet as well.
- **Source-insufficient / human-source-needed:** 38 (an editorial fragment with no
  datable primary source - preserve as manual with reason); 153 (Trump ICC
  sanctions - the identifiable action is EO 14203 signed 2025-02-06, so the
  2026-04-29 anchor needs a human sourcing decision, not a silent re-date).
- **Other deferred anchor / ticker cases:** 46 (Fed/OCC section-23A finding; the
  source date 2026-03-26 falls **outside** the c01 window, so any correction would
  move the row out of the current window and requires an explicit cluster /
  denominator restatement - high-consequence, held). The remaining L1A batch rows
  are all accounted for above (resolved live: 7, 29, 39, 154, 160, 239).

## 6. Why L1B is closed

- The known live date repairs (239, 154, 160) are **complete**.
- The known current-state carryovers those repairs created were **restated**:
  L1B-3A (239 dossier date + monetary span endpoint), L1B-3B (239 readout, sanction
  and ceasefire spans + sanction prose), L1B-3C (global independent-window capacity).
- **No known stale current-state aggregate from the completed L1B mutations
  remains.**
- The remaining work is **not** more date cleanup. The deferred rows need duplicate
  policy, ticker-attribution rulings, or human source decisions - policy and source
  work, which is the L2 phase.

## 7. L2 handoff

The L2 read-only inventory and impact probe (committed, descriptive only) establish
the current picture, reconfirmed for this closeout:

| scenario | accepted rows | clusters | c01 size | c01 S / C / U |
| --- | --- | --- | --- | --- |
| current baseline | 86 | 7 | 79 | 42 / 8 / 29 |
| conservative duplicate-only sensitivity | 83 | 7 | 76 | 39 / 8 / 29 |
| worst-case denominator sensitivity | 73 | 7 | 66 | 30 / 7 / 29 |

- The **cluster count stays 7** in every scenario and **c01 remains connected**;
  duplicate handling changes the row count and outcome composition, not the
  clustering.
- The denominator / outcome composition changes **materially** (support falls most:
  **12 of the 13** worst-case removable rows are support rows).

Therefore the L2 guidance is: **annotate first**; **do not silently replace the
86-row accepted denominator**; **source-pin the outcome-conflict groups G1 / G4 / G9
before** any bounded duplicate-adjusted counting; and keep **canonical story groups
deferred**.

## 8. Explicit next phase

- **L2A - source-pinning.** Source-pin the outcome-conflict groups G1 (30/42),
  G4 (39/53/54/64/70), and G9 (26/48/61) so a surviving date and outcome are
  defensible before any counting change.
- **L2B - annotation-only metadata.** Implement duplicate / same-story annotation
  (canonical-anchor link per member row), preserving every row, outcome, and
  readout, and changing no denominator.
- **L2C - bounded duplicate-adjusted count.** Expose a descriptive duplicate-adjusted
  count beside the 86 **only if** L2A resolves the ambiguous groups cleanly.

Live exclusion of any row is **not authorized** by this closeout.

## 9. Guardrails and non-claims

- Repaired anchors improve date **correctness**, not evidentiary independence; a more
  accurate date adds no data point and makes no mechanism true.
- Representative cases remain **illustrative** walkthrough material, not evidence.
- Any duplicate-adjusted count is **descriptive** unless and until a formal policy is
  adopted; it is not an effective sample size, a p-value, or an FDR figure.
- No statistical-significance claim; no forecasting claim.
- Not a trading, prediction, or recommendation surface, and it says nothing about the
  future returns of any asset.

## 10. Reproduction / state note

- **HEAD:** `cf2458496b30a925a3cfff53a34b314ab631ca79` (main == origin/main, 0/0).
- **events.db SHA-256:**
  `b950b22f10e8d660f08b98f61cf6589c5bdbde2b20477982a4453446ac5a7b98` - unchanged
  before and after this closeout (opened `mode=ro`).
- **price_cache.db SHA-256:**
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, size 0 bytes -
  not opened, unchanged.
- **Current K2 state:** 86 accepted rows / 7 clusters / largest 79; c01 42 / 8 / 29;
  global independent-window capacity 1d 19 / 5d 7 / 20d 3 over 19 distinct dates.
- **Current denominators:** archive 180 / accepted coverage 94 / accepted
  track-record 86 / event-study available 78 of 94 / staged candidates 13.
- **No DB or cache mutation** was performed in this closeout task; no provider or
  market-data API call, no `/analyze`, no fetch or backfill.
- Source artifacts inspected: `stats/L1_ANCHOR_REPAIR_BATCH.md`,
  `stats/L1B_REPAIR_PREVIEW.md`, `stats/L1B1_TEMP_DB_PROOF.md`,
  `stats/L1B2A_LIVE_REPAIR.md`, `stats/L1B2B_EXACT_DATE_GATE.md`,
  `stats/L1B2C0_TEMP_DB_PROOF.md`, `stats/L1B2C_LIVE_REPAIR.md`,
  `stats/EXPANDED_CASE_NOTES.md`, `stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md`,
  `stats/L2_DUPLICATE_CROSS_DATE_INVENTORY.md`,
  `stats/L2_DUPLICATE_POLICY_IMPACT_PROBE.md`,
  `stats/L2_DUPLICATE_POLICY_OPTIONS.md`.
