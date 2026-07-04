# L2 duplicate-policy impact probe (read-only, derived-view)

**Status:** read-only impact probe. Live `events.db` and `price_cache.db` were
**not** mutated and no temp database was written; the probe filters the live K2
accepted-row set in memory and re-runs the real `build_clusters` engine (a
read-only derived view). The live `events.db` SHA-256 is verified unchanged before
and after (`b950b22f...`). This note quantifies what candidate duplicate handling
*would* move so the L2 policy can be chosen with the numbers in hand; it decides
nothing and collapses nothing.

## 1. What a reviewer should take away first

- **The K2 descriptive cluster count is invariant: 7 clusters in every scenario,
  from baseline down to dropping 13 rows.** Every candidate row already sits in the
  c01 mega-cluster, so excluding candidates only *shrinks* c01 - it never
  disconnects it and never changes the cluster count. Duplicate handling is a
  **row-count and outcome-mix** question, not a clustering question.
- **The plausible denominator effect on the 86 accepted track-record rows runs
  from -3 (conservative) to -13 (worst-case), i.e. 86 down to 73.** c01 moves from
  79 to between 76 and 66.
- **The effect is overwhelmingly on the support tally.** 12 of the 13 worst-case
  drops are support rows, so c01 support falls 42 -> 30 while contradiction barely
  moves (8 -> 7) and unresolved is untouched (29). Cross-date re-ingestion inflates
  the support count more than any other outcome.
- **Annotate-only changes no existing number.** If the policy annotates rather than
  excludes (scenario 3), the accepted denominators, K2 numbers, outcomes, and
  readouts are all preserved; only a descriptive "22 candidate rows represent 9
  distinct stories" note is added.
- **Only the worst-case scenario touches a representative case** (row 61, in the
  coal group). Conservative and annotate-only leave all 15 representative cases and
  their cluster placement unchanged.
- These are **descriptive counts only**. None is an effective sample size, a
  p-value, or an FDR figure, and nothing here authorizes a live collapse.

## 2. Method

- **Engine.** The probe calls `scripts/effective_independent_evidence_report.py`
  `_assemble_rows(events.db)` to load the live 86-row accepted set with each row's
  date, primary ticker, outcome, event-study availability, and duplicate links,
  then re-runs the same `build_clusters` used by the K2 exhibit on **filtered
  copies** of that row list. No production code path is modified; no policy is
  implemented in the codebase.
- **Read-only.** `events.db` is opened `mode=ro` by the K2 loader; `price_cache.db`
  is never opened. The live SHA-256 is asserted equal before and after
  (`b950b22f10e8d660...`). No temp DB was created; filtering is in memory. No
  provider, API, network, `/analyze`, fetch, or backfill call was made.
- **Canonical survivor rule (for the exclusion scenarios).** Within a candidate
  group the earliest-dated row is kept and the later re-ingestions are the ones
  excluded from the denominator lens. This is a probe convention for measuring the
  bound, **not** a recommendation that the earliest row is the correct anchor -
  L1B source work pins the true date per group.
- **Baseline sanity.** The probe reproduces the live K2 exactly: 86 rows, 7
  clusters, c01 = 79, c01 split 42 / 8 / 29, corpus split 46 / 8 / 32,
  representative-in-largest 12 / 15, max non-overlapping 20d windows = 3.

## 3. Scenarios

1. **Baseline** - the live archive, no duplicate exclusion beyond current logic.
2. **Conservative duplicate-only** - exclude only the clear same-story,
   same-outcome re-ingestions (Lane B safe-to-collapse: G2 Artemis, G3 Barnsley,
   G5 tanker), keeping the earliest copy. Drops rows **49, 51, 44**.
3. **Broad same-story (annotate, no deletion)** - group all 9 candidate groups as
   same-story but delete nothing and drop no readout. Structural numbers stay at
   baseline; the only output is a descriptive duplicate-adjusted story count.
4. **Worst-case denominator sensitivity** - exclude *every* candidate member beyond
   the earliest in all 9 groups from an evidence-denominator lens. Drops 13 rows
   (**42, 44, 48, 49, 50, 51, 53, 54, 60, 61, 64, 70, 72**). This is the maximum
   plausible reduction, reported as a sensitivity bound only.

## 4. Results

All four scenarios, run against the live row set (c01 = the largest cluster
throughout):

| measure | S1 baseline | S2 conservative | S3 broad (annotate) | S4 worst-case |
| --- | --- | --- | --- | --- |
| rows excluded | 0 | 3 (49, 51, 44) | 0 (grouped, not dropped) | 13 |
| accepted track-record rows | 86 | 83 | 86 | 73 |
| descriptive cluster count | 7 | 7 | 7 | 7 |
| singleton clusters | 5 | 5 | 5 | 5 |
| largest cluster (c01) size | 79 | 76 | 79 | 66 |
| c01 support / contradiction / unresolved | 42 / 8 / 29 | 39 / 8 / 29 | 42 / 8 / 29 | 30 / 7 / 29 |
| c01 event-study rows | 67 / 79 | 64 / 76 | 67 / 79 | 54 / 66 |
| corpus support / contradiction / unresolved | 46 / 8 / 32 | 43 / 8 / 32 | 46 / 8 / 32 | 34 / 7 / 32 |
| representative cases in largest | 12 / 15 | 12 / 15 | 12 / 15 | 11 / 14 |
| max non-overlapping 20d windows | 3 | 3 | 3 | 3 |
| duplicate-adjusted story count (candidates) | - | - | 22 rows -> 9 stories | - |

## 5. Per-scenario detail

- **S1 baseline.** The live state. Nothing to implement; included as the reference.
  Safe for live: it *is* live.
- **S2 conservative duplicate-only (drop 49, 51, 44).** Accepted rows 86 -> 83; c01
  79 -> 76; c01 support 42 -> 39 (all three dropped rows are support); contradiction
  and unresolved unchanged; corpus 46 / 8 / 32 -> 43 / 8 / 32. Cluster count
  unchanged (7); no representative case dropped (12 / 15 preserved). These three
  groups are byte-identical-headline, same-outcome re-ingestions (two are
  non-market noise: Artemis, Barnsley; one is a same-ticker tanker copy), so the
  exclusion is unambiguous about the surviving label. **Denominator effect: -3 on
  the 86 lens.** Safe for live *only* as an explicit, provenance-recorded policy
  with the surfaces in section 6 restated - never a silent drop.
- **S3 broad same-story (annotate, no deletion).** All structural numbers stay at
  baseline (86 / 7 / 79, c01 42 / 8 / 29). The candidate set of 22 rows is annotated
  as representing 9 distinct stories - a descriptive **"distinct-story" count of 13
  fewer** than the nominal 22 - while every row, outcome, and readout is preserved.
  **Denominator effect: none.** This is the lowest-risk option and changes no
  existing exhibit; it only adds a story-grouping annotation.
- **S4 worst-case (drop 13).** Accepted rows 86 -> 73; c01 79 -> 66; c01 support
  42 -> 30, contradiction 8 -> 7 (the single dropped contradiction is row 61 in the
  coal group), unresolved unchanged; corpus 46 / 8 / 32 -> 34 / 7 / 32. One
  representative case is dropped (61), so representative-in-largest 12 -> 11 and
  total present 15 -> 14. Cluster count still 7; c01 remains connected. This assumes
  aggressive same-story collapse on groups whose true dates are not yet sourced
  (G6 / G7 / G8) and whose copies carry different tickers, so it is **a sensitivity
  ceiling, not a proposal**. **Denominator effect: -13 on the 86 lens (the maximum
  plausible).** Not safe to implement live as-is.

## 6. Denominator and surface impact map

The affected surfaces depend entirely on whether the policy **annotates** or
**excludes**:

- **Annotate-only (S3): no existing surface changes.** The denominator ledger, the
  K2 exhibit, the frontend effective-evidence card, the C01 narrative, and the
  family inventory all keep their current numbers; the policy adds one descriptive
  story-count line.
- **Exclude (S2 or S4): the accepted track-record denominator (86) itself moves,**
  which cascades to every surface that quotes it:
  - `stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md` (K2 golden exhibit) - c01 size,
    outcome split, ES ratio, event-id list.
  - `frontend/src/lib/effective-independent-evidence.ts` and the Evidence Overview
    tests - `largestClusterRows`, `representativeCasesInLargest`
    (`clusterCount` stays 7).
  - `README.md` reviewer-path line (largest-cluster row count).
  - `stats/C01_MARKET_NARRATIVE.md` - c01 size and the 42 / 8 / 29 split
    (hand-authored, line-by-line).
  - `stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md` - any family whose member rows
    were excluded (e.g. supply_shock loses the OPEC re-ingestions; the
    `geopolitical_conflict_context` count changes if 42 / 48 / 61 / 72 leave).
  - The denominator ledger (D1) on the Evidence Overview - the funnel
    180 / 94 / 86 / 78 / 13 would need an explicit restatement of the 86 (and 94)
    terms, treated as a deliberate denominator event, never a silent shift.

Because the K2 cluster count (7) is invariant, the headline "7 descriptive
market-story clusters" does **not** change under any scenario; only the
row-and-outcome figures do.

## 7. Safe-for-live assessment

| scenario | denominator effect | reps touched | cluster count | live-safe? |
| --- | --- | --- | --- | --- |
| S1 baseline | none | no | 7 | n/a (is live) |
| S2 conservative | -3 (86 -> 83) | no | 7 | yes, only as an explicit provenance-recorded policy with full restatement |
| S3 broad annotate | none | no | 7 | yes, lowest-risk; annotation only, no restatement needed |
| S4 worst-case | -13 (86 -> 73) | yes (61) | 7 | no; sensitivity bound only, not a proposal |

The material live-safety questions the numbers surface for the policy memo:
whether to move the accepted denominator at all (annotate vs exclude); how to
preserve row 61 as a representative case if the coal group is collapsed; and how to
record provenance for any excluded row.

## 8. Guardrails and non-claims

- This probe **mutates nothing** and implements no policy in code; it filters the
  live row set in memory and re-runs the read-only clustering.
- Every count here is **descriptive only**. The reduced row counts are **not** an
  effective sample size, not a p-value, not an FDR figure, and authorize no
  pooling. A duplicate-adjusted count is a legibility aid, not an inference.
- No event-study math was changed; no outcome label was changed; no representative
  case was reselected. Row 61's appearance in the worst-case drop is an arithmetic
  consequence of the sensitivity bound, not a recommendation to drop it.
- No row was collapsed, deleted, or redated; the archive evidence is intact.
- The closed Phase 1 / Phase 2 pools were neither read nor touched; their
  denominators stay separate and unchanged.
- No family-level inference; family lenses are context only.
- Not a trading, prediction, or recommendation surface, and it says nothing about
  the future returns of any asset.

## 9. Reproduction (read-only)

```
# reproduce the baseline K2 numbers this probe filters:
python scripts/effective_independent_evidence_report.py --db-path events.db --json

# the probe itself is a scratchpad-only, read-only derived view: it calls
# _assemble_rows(events.db) once, then re-runs build_clusters on in-memory
# filtered copies of the 86-row set for each scenario. No tracked helper, no
# temp DB, no live or cache mutation. Live events.db SHA-256 asserted equal
# before/after: b950b22f10e8d660f08b98f61cf6589c5bdbde2b20477982a4453446ac5a7b98.
```

- Candidate groups and canonical-survivor definitions are in
  `stats/L2_DUPLICATE_CROSS_DATE_INVENTORY.md`; the policy options that consume
  these numbers are in `stats/L2_DUPLICATE_POLICY_OPTIONS.md`.
- Source artifacts read: the K2 report generator, `stats/L1B1_TEMP_DB_PROOF.md`
  and `stats/L1B2C0_TEMP_DB_PROOF.md` (temp-DB method precedent), and
  `stats/L1B2C_LIVE_REPAIR.md` (the surface-restatement map reused in section 6).
