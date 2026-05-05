# Contributing

Second Order is maintained in focused, verifiable slices. Keep changes narrow, preserve existing API/UI contracts unless the task explicitly changes them, and prefer tests or zero-cost probes over assumptions.

## Workflow

- Work one focused slice at a time: backend behavior, frontend UI, docs, or hygiene.
- Run the relevant tests before committing. For cross-surface changes, run the full local verification set below.
- Keep local/quarantine artifacts out of commits: `.env`, local DBs, backups, caches, screenshots, generated reports, design scratch, and agent/session state.
- Use zero-cost probes and diagnostics before any paid path. For secrets and paid-action policy, see [SECURITY.md](SECURITY.md).
- Do not make paid provider calls from tests, CI, page load, refresh, or background polling.

## Local Verification

From the repo root:

```powershell
python -m unittest tests.test_validation_status tests.test_reaction_profile -v
python -m unittest tests.test_diagnostics tests.test_backfill_paid_guard -v
python -m unittest discover -s tests -p "test_events*.py" -v
npm --prefix frontend run typecheck
npm --prefix frontend run build
git diff --check
```

For frontend builds in restricted sandboxes, Vite/esbuild may fail with `spawn EPERM`; rerun the same build outside the sandbox. The Vite chunk-size warning is known and non-blocking.

## Commit Hygiene

Before committing:

```powershell
git status --short
git diff --check
```

Stage only intended source, tests, docs, and config files. Do not stage local databases, backups, generated build output, logs, reports, screenshots, or quarantine artifacts. If a file is unclear, leave it unstaged and document the decision.
