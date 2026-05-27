# Phase 2 FDR Policy v1

Sanitized public methodology document. Defines how false-discovery-rate (FDR) treatment applies to Second Order's Phase 2 expansion candidates. This artifact must exist before any Phase 2 candidate is tracked-promoted into the freeze cohort with a q-value claim.

## Scope and relationship to Phase 1

The Phase 1 frozen cohort (5 events: WHR / TXT / FSLR / RIO / LITE) was admitted under the prior regime and carries Benjamini-Hochberg q-values computed across its 5-row pool. Phase 1 q-values are frozen and are NOT recomputed when Phase 2 candidates are screened.

Phase 2 is a separate FDR scope. Its pool, its denominator, and its q-values are defined and computed independently of Phase 1.

## 1. Purpose

The FDR policy exists to control multiple-comparison error across Phase 2 candidate screens. It applies to a pre-registered expansion pool. It is NOT constructed after seeing screen results.

Raw p-values may be reported for interim candidates while the Phase 2 pool is open. q-values are computed only when the Phase 2 pool is closed, or when the operator explicitly freezes a defined subset of the pool.

## 2. Pool-lock rule

A Phase 2 FDR pool must be declared in a tracked artifact BEFORE any of its candidates are screened. The declaration must list, per candidate:

- `candidate_id`
- `primary_ticker`
- `benchmark_ticker`
- `event_date`
- `claimed_horizon` (single horizon from the pre-registered set {1, 5, 20})
- `expected_direction` (`positive` or `negative`)
- `mechanism_family`

Once screening begins for any candidate in the pool, the pool cannot be resized to improve q-values for any included row. New candidates added after the first screen in a pool form a separate pool or trigger BH recomputation under the incremental-pattern discipline (see Section 6).

Pool-lock violations are themselves recorded in the rejection log and the offending pool is invalidated.

## 3. Candidate inclusion

A candidate enters the FDR pool denominator only when ALL of the following are true:

- A valid pre-registered canonical test exists, committed to a tracked or local artifact before any data inspection.
- The candidate has been screened against the cohort's reference event-study engine (`stats.event_study.compute_event_study` with the cohort-default 60-bar estimation window and the production BHAR method).
- The primary claimed horizon's raw p-value has been computed.

Only the primary claimed horizon's p-value enters the BH calculation. Sibling-benchmark p-values, diagnostic-horizon p-values, and restricted-horizon p-values do NOT enter the primary FDR pool. They are reported in the per-row writeup as supporting context.

A candidate that fails the canonical test (wrong-sign, not-significant, or other rejection) STILL contributes its p-value to the denominator. The denominator is "all canonical tests attempted in this pool", not "all canonical tests that produced a favorable result." Removing a failed canonical test from the denominator after the fact would be selection bias.

## 4. Deferred candidates

A candidate flagged as `deferred_methodology_lesson` (e.g., CENX, NUE) counts in the project's selection / audit trail. It is recorded in `artifacts/rejection_log.json` and, where applicable, in this artifact's pool-history section.

A deferred candidate does NOT contribute a favorable p-value to the BH denominator unless it produced a valid pre-registered canonical test. Cache-only screens, exploratory diagnostics, and audit numbers from a deferred candidate are not canonical test results.

The "best available p" from a deferred candidate must never be used in the FDR pool. The operator cannot defer unfavorable candidates and retain favorable candidates from the same pre-screen exploration; doing so would be selection bias by deferral.

## 5. Interim treatment

While a Phase 2 pool is open (declared but not yet fully screened), candidates with completed canonical tests may carry:

- `raw_p`: reported.
- `q_bh`: `null`.
- An explicit `fdr_status` field set to `phase2_fdr_pending` with a pointer to this policy artifact and to the declared Phase 2 pool spec.

Any tracked promotion before pool closure must explicitly carry the `phase2_fdr_pending` caveat and must not present any q-value as the candidate's FDR-adjusted significance. Promotion under this interim state is operator-discretionary; the conservative posture is to hold promotion until the pool is closed (see Section 7).

## 6. Future q-value timing

q-values are computed when one of the following triggers fires:

- The Phase 2 pool is declared closed by the operator (all listed candidates have either completed canonical tests or been explicitly deferred / rejected with documented reason).
- The operator explicitly freezes a defined subset of the pool for the purpose of recording an FDR snapshot. The subset must be declared with the same per-candidate fields as the full pool, and the freeze must occur before any subsequent member is screened.

When q-values are computed, the artifact must record:

- The pool denominator (count of canonical tests included).
- All candidate p-values used (per `candidate_id`).
- The BH-adjusted q for each included candidate.
- The BH significance threshold (set to 0.05 for this cohort).
- A timestamp and the commit SHA of the pool spec at compute time.

q-values must be recomputed if active pool membership changes after the original computation. Prior q-values are preserved in the artifact's `revision_history` field. A row whose recomputed q exceeds the BH threshold is moved to `frozen_revised` or `frozen_deprecated` status per the methodology rubric's post-acceptance recourse vocabulary.

Two acceptable computation patterns:

- **Pattern P1 — pool-then-screen:** declare the full pool first, screen all members, compute BH once at pool closure. Mirrors the Phase 1 freeze pattern.
- **Pattern P2 — incremental with recomputation:** allow Phase 2 members to be added one at a time; every new screened member triggers BH recomputation across all included Phase 2 candidates; prior q-values archived under `revision_history`.

Pattern P1 is preferred for cohort discipline. Pattern P2 is permitted but the recomputation discipline is non-negotiable.

## 7. Recommended current decision (NVDA / Oct 17 2023)

The NVDA / SMH Oct 17 2023 BIS-update candidate has:

- A local pre-registration committed before any data inspection (`artifacts/cohort_integration_review_nvda_oct17_2023.json`).
- A local post-screen closeout recording `graduation_decision: graduate`, `graduation_status: with_caveat`, `borderline_gate: G2_ticker_benchmark` (`artifacts/cohort_integration_review_nvda_oct17_2023_post_screen.json`).
- Primary canonical test: NVDA / SMH h=1, raw p = 0.0081 (pre-registered direction: negative; realized: negative).

At the time NVDA was screened, no tracked Phase 2 pool spec existed. Under Section 2 of this policy, NVDA's screen does not have a defensible BH q-value because no pool was locked. Under Section 5, the recommended interim state is:

- **Do not assign `h1_q_bh` for NVDA.**
- **Hold tracked promotion of NVDA into `demo_artifacts/section_c_v2/freeze_candidate_evidence.json`**, OR promote only with `q_bh = null` and an explicit `fdr_status = phase2_fdr_pending` field pointing to this policy.

The preferred posture is to hold promotion until the Phase 2 pool is formally declared in a tracked artifact (e.g., `demo_artifacts/section_c_v2/phase2_pool_v1.json`) and at least one additional canonical test has been screened against it. That mirrors the Phase 1 pool-then-promote pattern and provides a non-trivial BH denominator.

NVDA's raw p of 0.0081 will clear BH at any reasonably-sized Phase 2 pool (BH-adjusted q at n=5 is approximately 0.04; at n=10 approximately 0.081, which would require operator reconsideration). This expectation is not a substitute for the actual q computation against a locked pool.

## Relationship to other tracked methodology artifacts

This policy is read alongside:

- `demo_artifacts/section_c_v2/methodology_acceptance_rubric_v1.md` — defines the per-candidate eight-gate rule and the graduation / post-acceptance vocabulary. G5 (FDR significant) references the FDR pool defined by this policy.
- `demo_artifacts/section_c_v2/rejection_log_summary_v1.json` — sanitized public summary of rejection decisions including deferred-methodology-lesson candidates.
- `demo_artifacts/section_c_v2/freeze_candidate_evidence.json` — the Phase 1 frozen 5-event cohort, whose q-values are pinned and not affected by this policy.

## Version history

- **v1** (2026-05-28): initial policy. Drafted in response to the NVDA / Oct 17 2023 candidate raising the question "what FDR pool does Phase 2 use?" with no pre-existing tracked answer. The policy itself is forward-only: it does not retroactively re-gate the Phase 1 cohort, and it does not retroactively assign a q-value to NVDA's pre-existing canonical test result. q-value assignment for NVDA, if pursued, will follow this policy under Section 6 once a Phase 2 pool is declared.

## What this policy is NOT

- Not a Phase 2 pool spec. A Phase 2 pool requires a separate tracked artifact listing candidate IDs and the fields enumerated in Section 2.
- Not a re-gate of the Phase 1 frozen cohort. Phase 1 q-values are pinned.
- Not authorization to assign any specific q-value to any specific Phase 2 candidate. Such assignment is the deliverable of a future operator step that closes a pool or freezes a subset.
- Not a substitute for the per-candidate writeup. Each Phase 2 candidate's source provenance, anchor convention, benchmark caveat, horizon classification, confounds, and falsifier remain per-candidate operator-stage work.
