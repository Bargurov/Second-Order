# Phase Evidence Methodology

Short tracked methodology note for Second Order's evidence layer:
the Phase 1 freeze bundle, the closed Phase 2 BH/FDR pool, the
sanitized rejection / deferred-lesson summary, and the schema
validators plus health smoke that gate them.

## What the evidence layer is

Four tracked artifacts plus their schema validators plus the project
health smoke:

- **Phase 1 freeze bundle** —
  `demo_artifacts/section_c_v2/freeze_candidate_evidence.json`. Five
  rows (WHR / TXT / FSLR / RIO / LITE), per-row pre-registered
  canonical test at h=1, BH q-values computed within the five-row
  Phase 1 denominator.
- **Phase 2 pool** —
  `demo_artifacts/section_c_v2/phase2_pool_v1.json` (closed pool)
  governed by
  `demo_artifacts/section_c_v2/phase2_fdr_policy_v1.md` (pool lock,
  candidate inclusion, deferred-row treatment, q-value timing).
- **Rejection / deferred summary** —
  `demo_artifacts/section_c_v2/rejection_log_summary_v1.json`.
  Sanitized public summary of rejections plus deferred methodology
  lessons.
- **Validators and health smoke** —
  `scripts/validate_freeze_candidate_artifact.py`,
  `scripts/validate_phase2_pool.py`,
  `scripts/validate_rejection_log_summary.py`, and the
  project-wide `scripts/project_health_check.py`.

The eight-gate acceptance rubric (G1–G8) and the post-acceptance
vocabulary used to describe each tracked row live at
`demo_artifacts/section_c_v2/methodology_acceptance_rubric_v1.md`.

## Phase 1 (freeze bundle)

Five rows: WHR / TXT / FSLR / RIO / LITE. Each row carries one
pre-registered canonical test at h=1 against the cohort-default
60-bar BHAR engine. BH q-values are computed across the five-row
Phase 1 denominator only.

Phase 1 q-values are frozen. They are **not** recomputed when a
Phase 2 candidate is screened. Phase 1 and Phase 2 are independent
FDR scopes by design (see `phase2_fdr_policy_v1.md` Sections 2 and
6).

## Phase 2 (closed BH/FDR pool v1)

Five canonical tests, denominator m=5, closed 2026-05-28:

| BH rank | Ticker | Benchmark | h=1 raw_p | q_bh    | Phase 2 BH at q≤0.05 |
|---|---|---|---|---|---|
| 1 | BA   | SPY | 3.2e-08  | 1.6e-07  | passes (BH/FDR discovery) |
| 2 | ALB  | SPY | 0.000044 | 0.00011  | passes (BH/FDR discovery) |
| 3 | NVDA | SMH | 0.0081   | 0.0135   | passes (BH/FDR discovery) |
| 4 | AMAT | SPY | 0.0527   | 0.065875 | fails (denominator member that failed G5/BH) |
| 5 | CF   | SPY | 0.161    | 0.161    | fails (denominator member that failed G5/BH) |

Three rows pass Phase 2 BH/FDR at q≤0.05: BA, ALB, NVDA. Two rows
(AMAT, CF) failed G5 at the raw-p threshold and also fail the BH
step-up. They remain in the denominator because their canonical
tests were attempted under pre-registered direction, benchmark,
and horizon. Removing a failed canonical test after the fact would
be selection bias.

q-values come from Benjamini-Hochberg step-up across the Phase 2
denominator only. Phase 2 q-values do not adjust against, and are
not compared with, Phase 1 q-values.

## Deferred methodology lessons

Some candidates were attempted but did not yield a defensible
pre-registered canonical test. They are recorded as deferred
methodology lessons and do **not** contribute to any BH denominator:

- **CENX** — delayed commodity repricing on the Rusal sanctions
  event; the canonical anchor convention ("last clean close before
  the market reacts") did not isolate a single clean h=1 window.
- **NUE** — multi-stage Section 232 steel-policy repricing; the
  policy unfolded over multiple announcements, so no single anchor
  cleanly isolates the relevant h=1 equity reaction.
- **NOC / BA (deferred row, distinct from the Phase 2 BA / 737 MAX
  canonical test)** — daily h=1 contaminated by adjacent earnings
  or FOMC releases, leaving G7 (no confound) non-defensible at the
  pre-registered horizon.

Deferred rows are documented in the audit trail and the
rejection-log summary. They are excluded from BH denominators
because no valid canonical test ran for them.

## Claims and non-claims

Claims:

- Tracked evidence artifacts pass their schema validators (Phase 1
  freeze artifact, Phase 2 pool, rejection-log summary, plus the
  project health smoke).
- Phase 2 pool v1 contains 5 canonical tests and yields 3 BH/FDR
  discoveries at q≤0.05 (BA, ALB, NVDA).
- Canonical tests that failed at raw-p or BH stay in the Phase 2
  denominator (AMAT and CF). No post-hoc removal.
- Deferred rows (CENX, NUE, NOC / BA-deferred) are documented and
  excluded from BH denominators because no valid canonical test
  ran for them.

Non-claims:

- Not live trading advice.
- Not a forecasting tool that produces forward-return estimates.
- Not a causal-mechanism claim. A row that passes the screen
  supports the pre-registered direction on the named event date;
  it does not establish causality.
- Not a complete universe of events. The cohort is a small curated
  bundle.
- Not a demo or presentation script.

## Reproducibility / validation

Each command reads its artifact in read-only mode and emits a
structured `{ok, errors, warnings}` envelope.

```
python scripts/project_health_check.py --json
python scripts/validate_freeze_candidate_artifact.py --artifact demo_artifacts/section_c_v2/freeze_candidate_evidence.json --json
python scripts/validate_phase2_pool.py --artifact demo_artifacts/section_c_v2/phase2_pool_v1.json --json
python scripts/validate_rejection_log_summary.py --artifact demo_artifacts/section_c_v2/rejection_log_summary_v1.json --json
```

`project_health_check.py` is the umbrella health smoke; the three
artifact validators each pin one artifact's schema. The
eight-gate rubric is read alongside these as documentation only —
it is not a runtime check.

See also: `demo_artifacts/section_c_v2/methodology_acceptance_rubric_v1.md`
and `demo_artifacts/section_c_v2/phase2_fdr_policy_v1.md`.
