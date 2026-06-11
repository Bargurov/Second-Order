# Transmission-case selection stress

**Date:** 2026-06-11
**Status:** read-only sensitivity diagnostic. The N1 selector and its six
primary cases are **unchanged**. No events.db / price_cache mutation. No new
denominator. No returns- or sector-based selection. No Q2 appendix built.

Reproduce:

```
python scripts/transmission_case_selection_stress_report.py --db-path events.db --json
python scripts/transmission_case_selection_stress_report.py --db-path events.db
```

## Why this report exists

Q0 found the six N1 walkthrough cases ([1, 61, 210, 46, 66, 211]) **defensible
but not yet robustly representative**. Q1 measures that: it re-runs the SAME
deterministic enrichment N1 uses (outcome bucket, family, info_score, anchor
label, event-study availability) under alternative selection policies and
reports how much the chosen set moves — without touching the N1 selector or
replacing the six cases. Selection never uses returns, AR/SAR/CAR, sector
data, or favorable outcomes.

## Current N1 selection and composition

| field | value |
|---|---|
| selected | 1, 61, 210, 46, 66, 211 |
| outcomes | support 3 · contradiction 1 · unresolved 2 |
| families | 6 distinct (tariff, conflict, supply_shock, monetary, ceasefire, sanction) |
| anchors | **clean 1** · partial_anticipation 2 · scheduled/weak 3 |
| event-study | available 6 / 6 |
| data-limited | 0 |
| multi-match or unclassified | 0 |

`reconstruction_consistent = true`: an independent re-implementation of N1's
role+family algorithm reproduces the six exactly, so the policy comparisons
below are apples-to-apples.

## Corpus-level comparison (the representativeness gap)

The 86 accepted rows are far more heterogeneous than the six:

- **outcomes:** support 46 · contradiction 8 · unresolved 19 · data-limited 13
- **event-study:** available 70 · **missing 16** (the six are all available)
- **families:** supply_shock 34 · unclassified **18** · tariff 12 · conflict 11
  · sanction 5 · monetary 3 · ceasefire 3; **16 multi-match** rows
- **anchors:** manual_review 57 · partial_anticipation 8 · scheduled/weak 8 ·
  duplicate 8 · **clean 5**
- **info_score:** {1: 9, 2: 7, 4: 53, 5: 17} — **17 rows tie at the top score**,
  so the event_id tie-break decides many fills.

So the six over-represent clean structure: all carry event-study coverage, all
are single-family matches, and only one carries a truly clean anchor.

## Policy comparison

Overlap with the current six, by deterministic policy (n = 6):

| policy | selected | overlap | dropped from current | notable |
|---|---|---|---|---|
| family_first | 1, 17, 26, 46, 66, 211 | 4/6 | 61, 210 | drops the contradiction guarantee (outcomes 5 support / 1 unresolved); adds 1 multi-match |
| outcome_first | 1, 61, 210, 17, 26, 46 | 4/6 | 66, 211 | keeps outcome roles; family mix shifts; adds 1 multi-match |
| anchor_quality_first | 1, 61, 210, 212, 225, 240 | 3/6 | 46, 66, 211 | replaces the three scheduled/weak rows with cleaner-anchored ones |
| missingness_aware | 31, 1, 61, 210, 46, 66 | 5/6 | 211 | **forces in an event-study-missing row (31)** the six omit |
| reverse_id_tiebreak | 71, 61, 240, 225, 218, 211 | 2/6 | 1, 210, 46, 66 | **only the tie-break changed, yet four of six flip** |

**No current id is retained by every alternative policy** (the intersection is
empty). Overlap ranges 2/6 → 5/6.

## Anchor-score policy check (disclosed, not fixed)

- **Documented:** info_score awards +1 for a *clean* event-date anchor.
- **Observed:** info_score awards the +1 to any anchor **not in**
  `_CAVEATED_ANCHORS` (`{manual_review_needed, continuation_or_thread_sibling,
  duplicate_or_deferred}`). In this corpus that silently includes
  **`partial_anticipation` and `scheduled_or_weak_anchor`** — non-clean anchors
  that nonetheless receive the "clean" bonus.
- **`mismatch_detected = true`.** Five of the six current cases carry one of
  these non-clean anchors and were treated as clean by the score.
- **Recommendation:** disclose only. A fix (tighten the clean test to
  `clean_discrete_anchor`, or correct the doc) is **out of Q1 scope** — Q1 does
  not change the N1 selector.

## What is stable

- Outcome diversity (≥1 support, ≥1 contradiction, ≥1 unresolved/limited) holds
  under current_n1, outcome_first, missingness_aware and reverse_id_tiebreak.
- The truly-clean unresolved supply_shock anchor (#210) survives the
  anchor-quality and outcome policies.

## What is sensitive

- **The specific fill ids.** No current case survives all five alternatives;
  reversing only the event_id tie-break flips four of six.
- **The omitted corpus regions.** No current case is data-limited,
  event-study-missing, multi-match or unclassified — yet `missingness_aware`
  and `family_first` show such cases are deterministically selectable.
- **The anchor lean.** Five of six lean on anchors the info_score mismatch
  rewards as clean.

## Whether Q2 is recommended

**Not required.** The case-selection sensitivity and the three composition gaps
(no data-limited/missing case, no multi-match/unclassified case, the
anchor-score doc/impl mismatch) are disclosed compactly in this report. Per the
Q1 rule, a Q2 appendix is warranted only if a gap cannot be disclosed
compactly — which is not the case here.

## Final recommendation

- **Keep the N1 six as primary** — they are defensible (deterministic,
  outcome-diverse, family-diverse) — but **state the three disclosed caveats**
  beside them (clean-structure lean, tie-break sensitivity, anchor-score
  mismatch).
- **Do not optimise the cases toward favorable outcomes** (Q1 never used
  returns or sector data, and the six should not be re-picked to look better).
- **Do not build a Q2 appendix** on this evidence; the disclosure here is
  sufficient.

## Non-claims

- This stress report does not replace N1; the six cases and the selector are
  unchanged.
- Representative cases are illustrative, not proof; n=1 per case; no single-event
  significance (no CI, p-value, FDR).
- No family-level inference and no performance ranking across cases or families.
- Selection uses only deterministic structural attributes — never returns,
  AR/SAR/CAR, sector availability, or favorable outcomes.
- Not a recommendation; no paid analysis; no database/price_cache mutation;
  nothing fetched or backfilled. Denominators unchanged (94 / 86 / 13).
