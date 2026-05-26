# Section C v2 — WHR + TXT Freeze-Ready Bundle

Two-row tracked freeze-candidate evidence bundle (schema_version: v2).

## Scope

This bundle contains **WHR / XLY** and **TXT / LMT** only. The other
three cohort candidates (CENX, FSLR, RIO) remain in the untracked
local artifact at `artifacts/freeze_candidate_evidence_v2.json`
pending their own source/provenance closeouts.

## Status

- `bundle_scope`: `whr_txt_two_row`
- `freeze_status`: `freeze_ready_pending_operator_review` (both rows)
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
| `freeze_candidate_evidence.json` | v2 WHR+TXT freeze-candidate artifact |
| `README.md` | This file |
