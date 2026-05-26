# Section C v2 — WHR-Only Freeze-Ready Bundle

WHR-only tracked freeze-candidate evidence bundle (schema_version: v2).

## Scope

This bundle contains **WHR / XLY only**. The other four cohort
candidates (CENX, FSLR, TXT, RIO) remain in the untracked local
artifact at `artifacts/freeze_candidate_evidence_v2.json` pending
their own source/provenance closeouts. They are not promoted here.

## Status

- `freeze_status`: `freeze_ready_pending_operator_review`
- Not frozen. Not wired to any demo endpoint.
- Section C Demo v1 (`demo_artifacts/section_c_v1/`) is unchanged.

## Validation

```
python scripts/validate_freeze_candidate_artifact.py \
    --artifact demo_artifacts/section_c_v2/freeze_candidate_evidence.json --json
```

## Contents

| File | Purpose |
|---|---|
| `freeze_candidate_evidence.json` | v2 WHR-only freeze-candidate artifact |
| `README.md` | This file |
