# Section C demo artifact bundle (v1)

A small, tracked demo artifact bundle the Section C demo can read from
when local `artifacts/` is empty or untracked. Five files only — no
provider data, no DB exports, no LLM output.

This is a **local demo input**, **not final research truth**. The files
are snapshots of operator-reviewed artifacts that have already been
validated by their respective gates; they are checked in so the demo
walkthrough is reproducible across machines.

## Files in this bundle

| File                                                | Role                                                                 |
|-----------------------------------------------------|----------------------------------------------------------------------|
| `analyzed_event_artifact_daily-demo-001.json`       | One reviewed, artifact-backed Daily candidate (operator-marked).     |
| `analyzed_event_artifact_daily-demo-002.json`       | One reviewed, artifact-backed Daily candidate (operator-marked).     |
| `analyzed_event_artifact_daily-demo-003.json`       | One reviewed, artifact-backed Daily candidate (operator-marked).     |
| `freeze_candidate_evidence.json`                    | Freeze-candidate evidence artifact for the Daily pilot cohort.       |
| `daily_reviewed_candidates.csv`                     | Operator's reviewed-candidate worksheet for the Daily cohort.        |

## What this bundle is

- A **demo artifact bundle** — five files only, copied verbatim from
  the operator's reviewed `artifacts/` directory at the point the
  bundle was promoted.
- The `freeze_candidate_evidence.json` file is the
  **freeze-candidate evidence** artifact: a snapshot of the
  pilot-cohort statistical summary at freeze time, awaiting operator
  approval before any downstream consumer may treat its claims as
  final.
- The bundle exists so the Section C demo backend has a stable set of
  inputs to read; it is not a substitute for the live, operator-
  reviewed `artifacts/` directory in real use.

## What this bundle is NOT

- **Not final research truth.** Every file here is a local demo
  input. Counts and verdicts surface as the artifact recorded them;
  the bundle adds nothing beyond what the underlying artifacts
  already say.
- **No FDR-significant claims** are made by this bundle unless the
  underlying `freeze_candidate_evidence.json` itself records an
  `fdr_significant` count greater than zero. As of this bundle the
  freeze-candidate evidence records `fdr_significant = 0` — no
  FDR-significant claim is supported.
- **Raw-p and FDR are separate measures.** A raw-p candidate signal
  is not FDR-significant and must not be reframed as one. The two
  counts live in distinct fields (`raw_p_candidate_count` and
  `fdr_significant_count`) and downstream consumers must keep them
  separate.

## Provenance

Files are direct copies (via `shutil.copy2`) of the inputs whitelisted
by `scripts/promote_demo_artifacts_preview.py`. No transformation,
re-derivation, or re-validation occurred during promotion. The
underlying artifacts are produced and validated by their own pipeline
scripts; this bundle is a tracked snapshot for demo reproducibility.

## Caution

These files are wired into the demo walkthrough only. Do not treat
their contents as a forecast, a trade signal, a backtest result, or
a research claim. The demo surface attaches a `caution_label` to
every item drawn from this bundle.
