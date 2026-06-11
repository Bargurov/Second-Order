# Accepted-family overlay review — weak-bucket diagnostics

**Date:** 2026-06-11
**Status:** read-only research review. No events.db write. No DB labels. No
denominator change. No paid analysis. Overlay-only.

Reproduce:

```
python scripts/accepted_family_overlay_review.py --db-path events.db --json
python scripts/accepted_family_overlay_review.py --db-path events.db
```

## Scope and denominators

Live archive denominators are unchanged by this review:

| denominator | value |
|---|---|
| archive rows | 180 |
| accepted coverage | 94 |
| accepted track-record (overlay target) | 86 |
| staged candidates | 13 |

The review consumes the J1 overlay
(`scripts/accepted_family_overlay_report.py`) as its source of truth for
bucket membership — it does not re-select the corpus and adds no denominator.

## Source J1 counts (overlay target = 86)

| bucket | count |
|---|---|
| single-match | 52 |
| multi-match | 16 |
| unclassified / review-needed | 18 |

52 + 16 + 18 = 86, matching the accepted track-record denominator.

## Why this review exists

J1 deliberately left two honest buckets rather than forcing every row into a
family: multi-match rows (more than one family matched) and unclassified rows
(no rule matched). This review explains, row by row, *why* each weak-bucket
row landed where it did, separates legitimate ambiguity from rule artifacts,
and proposes — never applies — bounded rule refinements. Labels stay in
memory; nothing is written to events.db.

Diagnosis method:

- **Multi-match** is diagnosed by the matched **family set** (a robust
  pattern, not a per-row hand label).
- **Unclassified** is diagnosed from a **curated snapshot** keyed to the
  frozen J1 buckets at HEAD `5921408`. Each curated entry carries an
  `expects` substring; the curated label is applied only when the row's
  headline still contains it, otherwise the row downgrades to `review_needed`.
  This makes the review self-invalidating if the underlying corpus drifts.

## Multi-match diagnostics (16 rows)

15 of 16 multi-match rows are **one legitimate structural overlap**; only 1
is a rule artifact.

| diagnosis | rows | family set |
|---|---|---|
| legitimate_overlap | 3, 11, 12, 32, 35, 36, 41, 47, 52 (9) | supply_shock + geopolitical_conflict_context |
| legitimate_overlap | 17, 63, 214, 291, 292 (5) | supply_shock + ceasefire_deescalation |
| legitimate_overlap | 37 (1) | sanction + supply_shock |
| overfit_risk | 250 (1) | tariff + geopolitical_conflict_context |

- **Conflict-driven supply disruption (9):** an oil / commodity token
  co-occurs with a conflict token (war, drone, refinery strike). Both
  channels are genuinely present; the canonical taxonomy has no single
  family for a conflict that is itself the supply shock. *Keep multi-match.*
- **Supply × de-escalation (5):** an oil / tanker token sits beside a
  ceasefire / peace / diplomacy token — the de-escalation reprices the very
  supply risk named alongside it. Two opposite-direction mechanisms in one
  headline. *Keep multi-match.*
- **Sanction-triggered supply threat (1, id 37):** a sanction token names the
  trigger and a Strait-of-Hormuz token names the channel. Cause and channel
  are both correctly present. *Keep multi-match.*
- **False overlap (1, id 250):** the conflict bucket's bare `war` token fires
  on the metaphor *trade war* in an otherwise pure tariff headline. The
  conflict tag is a rule artifact, not a second mechanism. *overfit_risk.*

## Unclassified / review-needed diagnostics (18 rows)

| diagnosis | rows | reading |
|---|---|---|
| off_topic_or_noise | 2, 4, 8, 9, 49, 51, 206, 207, 216, 236 (10) | archive noise — no market mechanism (space, crime, ceremony, trade-show, generic earnings) |
| taxonomy_gap | 25, 50, 101, 213, 235, 237 (6) | a real macro/policy event the canonical taxonomy has no family for (development/standards, trade-data, energy-tax, generic geopolitical-risk) |
| rule_miss_candidate | 34, 218 (2) | a row that belongs to an existing family but dodges the trigger tokens |

The two rule-miss rows are the only ones where the rules arguably *should*
have fired:

- **id 34** — a Strait-of-Hormuz supply-and-conflict row whose headline says
  "Strait remains blocked" (not the literal `hormuz` token) and
  "infrastructure" (not an oil token).
- **id 218** — a Saudi voluntary oil-supply cut whose headline carries none
  of the oil / opec / crude tokens; it uses "cuts" and "export reductions".

**Duplicate-headline note:** 3 of the 18 unclassified rows are exact-headline
duplicates of others in the same bucket — `2↔49`, `9↔51`, `25↔50`. The
bucket's effective distinct size is ~15, not 18.

## Pattern summary (counts across both weak buckets, 34 rows)

| category | count |
|---|---|
| legitimate_overlap | 15 |
| taxonomy_gap | 6 |
| terse / missing context | 0 |
| off_topic_or_noise | 10 |
| rule_miss_candidate | 2 |
| overfit_risk | 1 |
| review_needed | 0 |

15 + 6 + 0 + 10 + 2 + 1 + 0 = 34 = 16 multi + 18 unclassified.

There are **no** terse / missing-context rows in this snapshot: every
weak-bucket headline is a full sentence. The bucket weakness is overlap and
off-topic noise, not terseness.

## Candidate rule refinements (recommendations only — never applied)

Every refinement states a risk; none is written into J1 here.

| status | refinement | examples | risk |
|---|---|---|---|
| consider | literal `trade war` negative phrase on the conflict `war` token | 250 | war-metaphor exclusions are whack-a-mole; bounded to the literal phrase it is low-risk but narrow |
| defer | bounded `strait of hormuz` / `strait … blocked` phrase on supply_shock | 34 | `strait`/`blocked` are generic; single-row gain |
| reject | oil-supply-action phrasing (`export reduction`, `output cut`) as a **bare** keyword | 218 | bare `cut(s)` collides with rate / job / tax / price cuts — only a context-gated phrase is defensible |

## Rejected / deferred refinements (and what false positives they create)

- **Rejected — generic `geopolitics` catch-all bucket (25, 50):** most
  conflict and supply rows also mention geopolitics, so the bucket would
  swallow rows that belong to specific families and manufacture a meaningless
  mega-bucket. Fake coverage.
- **Rejected — auto-suppress off-topic noise (2, 8, 9, 206, 207):** hiding
  noise rows misrepresents the archive's heterogeneity and hardcodes a
  brittle lexicon. Honest practice is to leave non-market rows visibly
  unclassified.
- **Deferred — Hormuz phrase (34) and context-gated supply-cut phrase
  (218):** both gain a single row and need a tightly bounded, human-reviewed
  phrase. Defer to a separate gated task, not this read-only review.

## Taxonomy lessons

- **What the weak buckets reveal:** the multi-match bucket is not rule
  failure — it is the archive's core cluster (conflict-driven supply
  disruption and supply/de-escalation co-movement) sitting across two
  mechanisms the taxonomy cannot name with one family. The unclassified
  bucket is mostly genuine archive noise plus real macro/policy events with
  no canonical family; only 2 rows are true token misses.
- **What should not be forced:** the conflict × supply and supply ×
  de-escalation overlaps (do not pick a winner), the off-topic noise rows (no
  family should absorb them), and the generic-geopolitics rows (no catch-all
  bucket).
- **What can improve without a DB write:** a curated read-only second pass
  over only the 2 rule-miss rows with bounded context-gated phrases reviewed
  by a human; surfacing the duplicate rows; documenting the conflict/supply
  overlap as an explicit, named taxonomy limitation.

## How this updates ACCEPTED_FAMILY_OVERLAY

This review does not change J1's overlay, rules, counts, or denominators. It
adds a read-only diagnostic lens over J1's two weak buckets and records that:

- the 16 multi-match rows are 15 legitimate overlaps + 1 token artifact;
- the 18 unclassified rows are 10 noise + 6 taxonomy gaps + 2 rule misses,
  with 3 exact duplicates;
- the only headline-token misses worth a future rule change are ids 34 and
  218, and even those should be bounded and human-reviewed first.

## Non-claims

- Review diagnoses are research notes, **not DB labels**; the
  `mechanism_family` column was not read as truth and was not modified.
- No database write occurred anywhere in this review; price_cache untouched.
- No family-level inference, no family performance ranking, no
  validated-vs-contradicted comparison.
- No significance testing (no CI, p-value, or FDR); the closed Phase 1 /
  Phase 2 FDR pools are neither read nor reopened.
- Not a recommendation of any kind; the `recommendation` fields are curation
  notes about the rules, not market guidance.
- No paid analysis was run and none is approved; paid `/analyze` remains
  blocked.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record.

## Final recommendation

- **Keep this review read-only.** It is a diagnostic lens, not a labeling
  task.
- **Do not write DB labels.** The `mechanism_family` column stays untouched.
- **Do not automatically apply any refinement.** Every proposed change is a
  recommendation with a stated risk.
- **Consider a later K2 rule-refinement task only after reviewing this
  report**, and only for the bounded, human-reviewed cases (250 `trade war`
  negative phrase; 34 / 218 context-gated phrases). The generic-geopolitics
  catch-all and the noise auto-filter are rejected outright.

> **Second lens (L1):** the mechanism-text lens that K1 suggested has now been
> tested read-only in
> [`stats/ACCEPTED_FAMILY_SECOND_LENS.md`](ACCEPTED_FAMILY_SECOND_LENS.md) /
> `scripts/accepted_family_second_lens_report.py`. It recovers exactly the
> rule-miss rows named above (218, 34) but doubles multi-match (16 → 32) and
> needs review on 12 rows — so a K2 should stay narrow to those named rows,
> not a corpus-wide second-lens reclassification.
