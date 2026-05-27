# Methodology Acceptance Rubric v1

Sanitized public summary of the cohort-integration rule applied to current and future Second Order freeze-candidate cohorts. The full local rule, the adversarial-review notes that drove v1, and per-candidate review blocks are operator-local and not part of this tracked artifact.

## Scope

This rubric governs the admission of *future* expansion candidates into the freeze cohort. The five existing v2 cohort members (WHR / TXT / FSLR / RIO / LITE) were admitted under a prior, looser regime and are exempt from retroactive re-gating, per the rule's forward-only clause.

## The eight gates

For each candidate, the operator answers eight yes/no questions. All eight must be `yes` for the candidate to graduate into the cohort.

| Gate | Question | Phase |
|---|---|---|
| G1 | Source quality acceptable? Primary issuer (regulator, exchange, company) with unambiguous timestamp. | pre-test |
| G2 | Ticker / benchmark defensible? Operator names 1–2 alternative proxies considered and explains the choice. | pre-test |
| G3 | Mechanism direction registered before the test was run? | pre-test |
| G4 | Event NOT selected because the result was good? | pre-test |
| G5 | FDR significant at q ≤ 0.05 against the pre-registered pool? | post-test |
| G6 | Horizon in pre-registered set {1, 5, 20} and defensible for the mechanism? Pre-test rationale committed before the smoke runs. | pre-test (set + rationale) + post-test (which horizon) |
| G7 | No obvious concurrent confound dominating? FOMC, earnings, M&A, geopolitical shock within ±2 trading days are always confounds. | pre-test (scan committed before smoke) + post-test (benchmark anomaly check) |
| G8 | Operator can defensibly explain the candidate's mechanism in a short oral or written defense to a domain reviewer? Explanation committed before the smoke runs. | pre-test |

A single `no` blocks graduation. The candidate stays in its expansion-batch artifact and is not merged into the freeze cohort.

## Graduation decisions

| Decision | Meaning |
|---|---|
| `graduate` | All eight gates `yes`. Row merges into the freeze cohort. |
| `hold` | At least one `no`. Row remains in the expansion batch for possible re-evaluation in a future round. |
| `reject` | At least one `no` with no expectation of re-evaluation. |

## Graduation status

A graduated row carries a status distinct from its decision:

| Status | Meaning |
|---|---|
| `clean` | All eight gates `yes` with no borderline notes. |
| `with_caveat` | All eight gates `yes` but one or more carry a borderline note that the operator records as a known weakness. The borderline gate is named in the block. The caveat is propagated to the per-row caveat field in the freeze artifact when the row is merged. |

## Post-acceptance challenge and recourse

A row already in the freeze cohort may be challenged after the fact for source error, date error, confound discovery, or benchmark concern. v1 defines three status values for challenged rows:

| Status | Meaning |
|---|---|
| `frozen_revised` | Numbers updated (e.g., source-quality correction); methodology and mechanism interpretation unchanged. Row stays in the cohort. Cohort-level FDR q-values are recomputed. |
| `frozen_deprecated` | Row removed from cohort statistics but retained in the record with a written deprecation note. Cohort-level q-values are recomputed without it. |
| `deferred_methodology_lesson` | Row moved to deferred-lesson status. Does not enter cohort statistics; revisitable only after a fresh pre-registration under updated methodology. |

Silent patching of a tracked row's numbers, anchor, source, or benchmark is prohibited. Any such change requires an explicit status transition and a written reason note.

The recourse path is forward-only. It does not authorize retroactive status changes without an explicit, documented challenge.

## Rule version

v1, dated 2026-05-27. Schema for per-candidate review blocks is enforced by `scripts/validate_cohort_integration_review.py`.

## What this rubric is NOT

- Not a claim of causal mechanism, durable repricing, or persistent edge for any cohort row.
- Not a re-gate of existing cohort members.
- Not authorization to merge any specific candidate — operator review is the final step.
