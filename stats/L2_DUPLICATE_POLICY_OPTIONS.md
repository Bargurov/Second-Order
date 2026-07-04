# L2 duplicate-policy options memo (design note)

**Status:** policy design note. It proposes no mutation, changes no code, and
touches no database; it frames how Second Order should treat duplicate and
cross-date same-story rows so a later slice can pick a policy deliberately. It
consumes the read-only inventory (`stats/L2_DUPLICATE_CROSS_DATE_INVENTORY.md`) and
impact probe (`stats/L2_DUPLICATE_POLICY_IMPACT_PROBE.md`). Any implementation is a
separate, explicitly gated task.

## 1. What a reviewer should take away first

- **The problem is counting, not clustering.** K2 already groups the 22 candidate
  rows into the c01 mega-cluster, and the impact probe showed the descriptive
  cluster count stays **7** under every scenario. What is still counted several
  times is the nominal row count and the outcome mix (support especially: 12 of the
  13 worst-case-droppable rows are support rows).
- **This is a descriptive-layer decision, not an evidence-track reopening.**
  Duplicate handling operates on the K2 / accepted track-record **description** of
  the archive. The closed Phase 1 / Phase 2 FDR pools are out of scope and stay
  untouched; nothing here becomes a p-value or an FDR figure.
- **Three coherent policies exist**, in ascending machinery and ambition: **A**
  annotate-only (no exclusion), **B** a separate descriptive duplicate-adjusted
  evidence count beside the 86, and **C** a canonical-story-group model with all
  member rows preserved.
- **Recommendation (PM guidance):** ship **A now**, because it is reversible,
  needs no denominator restatement, and matches the descriptive-only stance of the
  K2 layer; add a **bounded B** as a second descriptive lens *after* L1B source
  work pins the true dates for the outcome-conflict groups (G1 / G4 / G9); hold
  **C** unless the archive grows enough that ad-hoc annotation stops scaling. This
  is a sequencing judgment, not a claim that any option is statistically superior.

## 2. Answers to the policy questions (shared across all options)

These answers are policy invariants: whichever option is chosen, they hold.

**Q1. When is a row an exact duplicate versus a related observation?**
- **Exact duplicate:** same `headline` and same `event_date`. Archive-wide there is
  exactly one such pair (`[302, 315]`), and none among the L2 candidates.
- **Cross-date same-story re-ingestion:** identical (or near-identical) headline on
  *different* ingestion dates - all nine candidate groups. These are one news story
  re-saved, and should be treated as one observation.
- **Same macro saga, potentially distinct:** rows about the same ongoing situation
  but plausibly distinct reporting moments (the OPEC saga G4 is the only borderline
  case); the safest reading is still one cartel action, one observation.
- **Related observation (keep separate):** rows sharing a theme or ticker but a
  genuinely different event - these are NOT duplicates and must not be collapsed.

**Q2. Exclude, annotate, collapse, or link?** These are the three options in
sections 4-6. The invariant is that *whatever* is done is **descriptive** and
**reversible in meaning**: the underlying rows and their readouts are never
destroyed, and the K2 cluster count (7) is never presented as changed by duplicate
handling (it is not).

**Q3. Should representative cases include duplicate-linked rows?** Yes, but the
**canonical (surviving) member** should carry the representative role, never a
deferred sibling. Row 61 (coal group, an N1 anchor) and row 30 (fighter-jet, the
family-inventory representative) must be preserved as representatives; if their
group is collapsed, the representative is **re-anchored to the canonical row**, not
dropped. A representative case is never removed merely to make a collapse tidy.

**Q4. How should outcome counts display duplicate-linked rows?** The headline
outcome counts stay on the full accepted set (corpus 46 / 8 / 32; c01 42 / 8 / 29),
with each duplicate-linked row carrying a visible duplicate flag. A
duplicate-adjusted outcome line may sit **beside** the headline counts, never
replacing them. Contradiction rows (e.g. 61) are never hidden to make a group read
as coherent support.

**Q5. How are event-study readouts preserved if rows are collapsed from a
denominator lens?** The surviving canonical row keeps its readout; deferred
siblings keep their readouts as **linked context**, not dropped. Identical-window
readouts on the same story are the same tape (K2 already flags this as the
"shared primary" caution), so they are shown as one readout observed several times,
not several readouts. Event-study math is never recomputed to force a merge.

**Q6. The five counts, kept distinct.**

| count | current value | what it is |
| --- | --- | --- |
| archive row count | 180 | every stored row, all stages |
| accepted row count | 94 coverage / 86 track-record | rows in the accepted lenses (two lenses, kept apart) |
| market-story cluster count | 7 | K2 descriptive clusters over the 86; invariant under duplicate handling |
| duplicate-adjusted evidence count | proposed (descriptive) | 86 minus cross-date re-ingestions, a legibility aid; range 73-83 per the probe |
| representative cases | 15 | illustrative walkthrough cases, not evidence |

**Q7. UI language so a finance reviewer does not read duplicate handling as
proof.** Any duplicate-adjusted count is labelled a "descriptive de-duplicated
story count" / "independence caution", explicitly **not** an effective sample size,
not a p-value, not significance, and not an FDR figure - reusing the existing K2
non-claim wording. It is not a trading, prediction, or recommendation surface.

**Q8. What must never happen (hard invariants for any option).**
- No row is deleted without a preserved before/after provenance record (Phase-K
  correction convention).
- No outcome label is changed to force a group into coherence.
- No contradiction row is hidden to make a story read as clean support.
- No duplicate-adjusted count is presented as, or combined into, a p-value, an FDR
  pool, or the closed Phase 1 / Phase 2 denominators.

## 3. Design constraints from the project

- **Descriptive, not inferential.** Second Order is a research dashboard, not a
  trade tool; duplicate handling improves honesty of counting, it does not create
  or destroy evidence.
- **Pools stay separate.** Phase 1 and Phase 2 are never combined into one
  denominator; the closed evidence track is not reopened by this work.
- **Two accepted lenses stay apart** (94 coverage vs 86 track-record); a
  duplicate-adjusted count must state which lens it adjusts.
- **No paid calls, no fetch, no `/analyze`** in any implementation of these
  options; the row data is already in the archive.

## 4. Option A - annotate-only, no exclusion

Mark cross-date same-story members with a duplicate link and a canonical-anchor
pointer; **exclude nothing**. Every denominator stays where it is; the archive
gains a "these N rows are one story" annotation.

- **Benefits.** Lowest risk; reversible; no denominator event; preserves all rows,
  outcomes, and readouts; matches the K2 layer's descriptive stance; requires no
  restatement of the funnel, the K2 exhibit, the frontend card, or the family
  inventory. Impact probe scenario S3: all structural numbers unchanged.
- **Risks.** The headline denominator (86) and its support count stay visibly
  inflated by re-ingestion; the reviewer must do the mental adjustment. Annotation
  can be missed if it is not surfaced next to the counts it qualifies.
- **Implementation surface.** A duplicate-link + canonical-anchor field per member
  row (or a small side table), populated read-only from the inventory groups; a
  render change to show the flag. No change to scoring, clustering, or denominators.
- **Tests needed.** A test that the annotation never changes any denominator,
  outcome, or cluster count; a test that every candidate member carries a canonical
  pointer; a banned-framing test on the new copy.
- **Report / UI changes.** A duplicate-link column or footnote on the K2 and c01
  surfaces; one explanatory sentence. No number moves.
- **Appropriateness.** Strong fit for the current project stage: honest, cheap,
  reversible, and it does not disturb the finished evidence track.

## 5. Option B - exclude duplicate-linked rows from an effective-evidence denominator only

Keep the archive and accepted denominators at 86, but publish a **separate,
clearly-labelled duplicate-adjusted evidence count** (86 minus the later
re-ingestions) as a second descriptive lens on the K2 / effective-evidence surface.
Rows are excluded only from *that* lens, never from the archive.

- **Benefits.** Makes the effective-evidence reading honest about re-ingestion
  without deleting anything; quantified and bounded (probe: 83 conservative, down to
  73 worst-case); leaves the 86 track-record and 94 coverage lenses intact for
  continuity. The support-count inflation becomes visible (c01 support 42 -> 39 or
  30) rather than implicit.
- **Risks.** A new count to explain; risk a reviewer reads it as an effective
  sample size or a corrected denominator - must be labelled descriptive-only and
  kept beside, never replacing, the 86. The surviving-outcome choice for the
  outcome-conflict groups (G1 / G4 / G9) is a judgment that must be sourced first.
- **Implementation surface.** Option A's annotation plus a derived
  duplicate-adjusted count on the effective-evidence layer (a filter over the
  existing K2 rows, exactly the probe's derived view); no scoring or FDR change.
- **Tests needed.** Option A's tests plus: the duplicate-adjusted count equals the
  probe's number for the chosen group set; the 86 / 94 denominators and the cluster
  count (7) are unchanged; the closed FDR pools are untouched; a copy test that the
  adjusted count carries the "not an effective sample size" non-claim.
- **Report / UI changes.** A second line on the K2 exhibit and the Evidence Overview
  effective-evidence card ("descriptive duplicate-adjusted story count: NN of 86");
  the denominator ledger stays at 86 with a footnote pointing to the adjusted lens.
  No frontend `clusterCount` change (still 7).
- **Appropriateness.** A good *second* step once the outcome-conflict groups are
  source-pinned; premature before that, because the adjusted count would bake in an
  unsourced surviving-outcome choice.

## 6. Option C - canonical story groups, member rows preserved

Introduce an explicit story-group model: each cross-date group gets a canonical
anchor row and its members are marked duplicate-deferred context, mirroring the
sanction thread-collapse convention (E1). Both the annotate view (A) and the
adjusted-count view (B) then derive from the same stored grouping.

- **Benefits.** Single source of truth for story grouping; full provenance;
  supports both the annotate and adjusted-count readings without ad-hoc lists;
  scales as the archive grows; consistent with the existing thread-collapse pattern
  for staged sanctions.
- **Risks.** Largest implementation and review surface; a story-group schema and a
  canonical-anchor decision per group (including the sourced surviving date/outcome
  for G1 / G4 / G9); more places for a subtle denominator error to hide; heaviest to
  verify. Over-engineered for nine groups.
- **Implementation surface.** A story-group table (group id, canonical row, member
  rows, provenance) and read-only derivations for A and B; source-pinned canonical
  choices for the conflict groups.
- **Tests needed.** Grouping integrity (every member maps to exactly one group and
  one canonical anchor); denominators and cluster count invariant; representative
  cases re-anchored to canonical rows, never dropped; provenance present for every
  grouped row; banned-framing.
- **Report / UI changes.** Same surfaces as B, plus a story-group view; the C01
  narrative gains a canonical-anchor column.
- **Appropriateness.** Right destination *if* duplicate handling becomes a
  recurring, growing need; disproportionate for the current nine groups, where A
  (and a bounded B) deliver most of the value at a fraction of the cost.

## 7. Recommendation (PM guidance)

- **Now: Option A (annotate-only).** It is reversible, needs no denominator event,
  changes no existing number, and immediately makes the re-ingestion structure
  visible. It is the honest, low-cost step and fits the finished-evidence-track
  constraint.
- **Next, gated: bounded Option B.** Add a single descriptive duplicate-adjusted
  evidence count beside the 86 *after* L1B source work pins the true dates and
  surviving outcomes for the outcome-conflict groups (G1 fighter-jet, G4 OPEC saga,
  G9 coal). Until then, restrict any adjusted count to the conservative,
  same-outcome groups (G2 / G3 / G5), whose collapse is unambiguous (probe: 86 ->
  83, no representative touched).
- **Later, only if needed: Option C.** Adopt the story-group model only if the
  archive grows enough that per-group annotation stops scaling; for nine groups it
  is more machinery than the problem warrants.

This sequencing is a project-management judgment about risk and reversibility, not
a statistical claim: no option is "more significant" than another, because none of
them produces significance. A, B, and C differ only in how much descriptive
machinery they add to the same honest counting story.

## 8. Guardrails and non-claims

- This memo designs a policy; it implements nothing and mutates nothing.
- Duplicate handling is descriptive: it changes how rows are counted and labelled,
  never whether a mechanism is true. It creates and destroys no evidence.
- No duplicate-adjusted count is an effective sample size, a p-value, an FDR figure,
  or a significance claim; the closed Phase 1 / Phase 2 pools stay separate and
  untouched.
- No row is deleted without provenance; no outcome is changed to force coherence;
  no contradiction row is hidden.
- No family-level inference; family lenses are context only.
- The section 7 recommendation is internal project-management guidance about how to
  count rows; it is not investment advice, a price prediction, or a directional call
  on any asset, and it says nothing about future returns.

## 9. Inputs (read-only)

- `stats/L2_DUPLICATE_CROSS_DATE_INVENTORY.md` - the nine candidate groups and
  their classifications.
- `stats/L2_DUPLICATE_POLICY_IMPACT_PROBE.md` - the four-scenario impact numbers
  reused throughout.
- `stats/L1_ANCHOR_REPAIR_BATCH.md`, `stats/L1B_REPAIR_PREVIEW.md` - the source
  basis for the groups and the thread-collapse convention this memo mirrors.
- No database, provider, API, network, `/analyze`, fetch, or backfill call was made
  in writing this memo.
