# Section C v2 — Tracked Phase 1 + Phase 2 Evidence

Tracked evidence artifacts for Second Order's evidence layer. The
bundle spans the Phase 1 freeze cohort and the closed Phase 2 BH/FDR
pool, plus the sanitized rejection / deferred-lesson summary and the
policy and rubric documents that gate them.

## Contents

| File | Purpose |
|---|---|
| `freeze_candidate_evidence.json` | Phase 1 freeze-candidate bundle: WHR / TXT / FSLR / RIO / LITE. Five rows, each with a pre-registered canonical test at h=1 and a BH q-value computed within the five-row Phase 1 denominator. |
| `phase2_pool_v1.json` | Closed Phase 2 BH/FDR pool: BA / ALB / NVDA / AMAT / CF. Five canonical tests; three BH/FDR discoveries at q≤0.05 (BA, ALB, NVDA); two denominator members that failed G5 and BH (AMAT, CF). Pool closed 2026-05-28. |
| `phase2_fdr_policy_v1.md` | Phase 2 FDR policy: pool-lock rule, candidate inclusion, deferred-row treatment, interim language while a pool is open, and q-value timing. Forward-only — does not retroactively re-gate Phase 1. |
| `rejection_log_summary_v1.json` | Sanitized public summary of rejections, deferred methodology lessons (CENX, NUE, NOC), and audit-trail counts. Used to track decisions outside the BH denominators. |
| `methodology_acceptance_rubric_v1.md` | Per-candidate eight-gate rule (G1–G8) and post-acceptance vocabulary used to describe each tracked row. Documentation only, not a runtime check. |
| `phase_evidence_methodology.md` | Cohort-wide methodology note: what the evidence layer is, Phase 1 vs Phase 2 scope separation, deferred methodology lessons, claims / non-claims, and reproducibility commands. |
| `phase_history.md` | Phase 1 through Phase 4 history and the closeout note. Records the tracked deliverables that close the evidence track. |
| `README.md` | This file. |

## Phase 1 vs Phase 2 scopes

Phase 1 and Phase 2 are independent FDR scopes. Phase 1 q-values are
pinned to the five-row Phase 1 denominator and are **not** recomputed
when a Phase 2 candidate is screened. Phase 2 q-values come from
Benjamini-Hochberg step-up within the Phase 2 pool only. The two
scopes are kept distinct by design in `phase2_fdr_policy_v1.md`.

## Methodology summary

The cohort-wide methodology — what the evidence layer is, claims,
non-claims, and reproducibility commands — lives at
[`phase_evidence_methodology.md`](phase_evidence_methodology.md).
The Phase 1 through Phase 4 arc and the closeout note live at
[`phase_history.md`](phase_history.md). Both files are in this
same directory.

## Validation

```
python scripts/validate_freeze_candidate_artifact.py --artifact evidence_artifacts/section_c_v2/freeze_candidate_evidence.json --json
python scripts/validate_phase2_pool.py --artifact evidence_artifacts/section_c_v2/phase2_pool_v1.json --json
python scripts/validate_rejection_log_summary.py --artifact evidence_artifacts/section_c_v2/rejection_log_summary_v1.json --json
python scripts/project_health_check.py --json
```

## Status

- `bundle_scope`: `whr_txt_fslr_rio_lite_five_row` (Phase 1 freeze cohort)
- Phase 1 freeze status: `freeze_ready_pending_operator_review` for all five Phase 1 rows
- Phase 2 pool: closed 2026-05-28 with three BH/FDR discoveries
- Read-only consumption surface: the tracked `GET /evidence/summary` route (Phase 4). Section C Demo v1 (`evidence_artifacts/section_c_v1/`) is unchanged.
