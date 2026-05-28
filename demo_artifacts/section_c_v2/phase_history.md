# Phase History — Tracked Evidence Track

Records the Phase 1 through Phase 4 arc of Second Order's tracked
evidence track. The arc is closed at Phase 4. Future work is separate
and not scheduled by this document.

For the cohort-wide methodology — what the evidence layer is, the
claims and non-claims, and the reproducibility commands — see
[`phase_evidence_methodology.md`](phase_evidence_methodology.md) in
this same directory.

## Phase 1 — Freeze cohort

A five-row freeze-candidate cohort lives at
[`freeze_candidate_evidence.json`](freeze_candidate_evidence.json):
WHR, TXT, FSLR, RIO, LITE. Each row carries a pre-registered
canonical test at the claimed horizon h = 1.

Phase 1 is its own FDR scope. Each row's BH-adjusted q-value was
computed inside the five-row Phase 1 denominator and is frozen at
that value. Phase 1 q-values are not recomputed against any later
scope.

## Phase 2 — Closed BH/FDR pool

A five-row BH/FDR pool lives at
[`phase2_pool_v1.json`](phase2_pool_v1.json): BA, ALB, NVDA, AMAT,
CF. Each row carries one pre-registered canonical test at the
claimed horizon h = 1. The pool was closed on 2026-05-28 under the
policy at
[`phase2_fdr_policy_v1.md`](phase2_fdr_policy_v1.md).

BH/FDR discoveries at the q ≤ 0.05 threshold: BA, ALB, NVDA.

Denominator members that did not pass the screen: AMAT and CF.
Their canonical tests were attempted before pool closure, so they
remain in the five-row denominator per the closed-pool policy. They
are not BH/FDR discoveries.

Phase 2 is a separate FDR scope from Phase 1. The five Phase 2
q-values come from Benjamini-Hochberg step-up within the Phase 2
pool only. They are not mixed with Phase 1 q-values at any stage of
the pipeline.

Deferred methodology lessons (CENX, NUE, NOC) are recorded in
[`rejection_log_summary_v1.json`](rejection_log_summary_v1.json).
They are not denominator members of this pool and are not BH/FDR
discoveries; they are documented separately so the methodology
record stays complete.

## Phase 3 — Validators, loader, health check, CI gate, methodology doc

Phase 3 added the machinery that protects the tracked evidence
layer from silent regression:

- Three schema validators —
  `scripts/validate_freeze_candidate_artifact.py`,
  `scripts/validate_phase2_pool.py`, and
  `scripts/validate_rejection_log_summary.py` — each read-only and
  each refusing artifacts that drift from their pinned shape.
- `cohort_evidence.py` — a read-only loader that normalizes Phase 1
  and Phase 2 rows into one consumable record shape while preserving
  the FDR scope separation pinned by the artifacts themselves.
- `scripts/project_health_check.py` — the `evidence_layer` section
  pins the per-phase counts
  (`phase1_count = 5`, `phase2_count = 5`, `phase2_pass_count = 3`,
  `phase2_fail_count = 2`, `deferred_count = 3`) and surfaces them in
  the project-wide health report.
- `.github/workflows/ci.yml` — a CI gate runs the four evidence test
  modules and the three validator command-line interfaces on every
  push and pull request, and asserts the project-health
  evidence-layer counts against the pinned baseline.
- [`phase_evidence_methodology.md`](phase_evidence_methodology.md) —
  the cohort-wide methodology note covering what the evidence layer
  is, the Phase 1 / Phase 2 scope separation, deferred methodology
  lessons, claims and non-claims, and reproducibility commands.

## Phase 4 — Tracked-only evidence summary endpoint

`GET /evidence/summary` exposes the tracked evidence layer as a
read-only JSON view. The route:

- reads only from `demo_artifacts/section_c_v2/`;
- does not read from local operator artifact paths under
  `artifacts/` or from any per-row operator writeup;
- does not touch the events database, the price cache, any external
  provider, or the network;
- preserves Phase 1 and Phase 2 as separate FDR scopes by reusing
  `cohort_evidence`'s per-phase split;
- reports the same pinned counts the project-health
  evidence-layer section reports.

## Closeout

The tracked evidence track is complete through Phase 4. The full set
of tracked deliverables is:

- the five-row Phase 1 freeze-candidate cohort and its read-only
  schema validator;
- the closed five-row Phase 2 BH/FDR pool, its policy document, and
  its read-only schema validator;
- the sanitized rejection / deferred-methodology-lesson summary and
  its read-only schema validator;
- the methodology acceptance rubric and the cohort-wide methodology
  note;
- the `cohort_evidence` loader;
- the project-health `evidence_layer` section and the CI evidence-
  layer gate;
- this phase-history record;
- the tracked-only `GET /evidence/summary` route.

No new candidates, new pools, or new validators are scheduled by
this document. Any future work on top of this layer (a UI readout,
additional endpoints, telemetry, broader integration) is
intentionally not scheduled here and would constitute a separate
track.
