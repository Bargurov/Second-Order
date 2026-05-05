# Public Repo Cleanup Plan

Purpose: classify the remaining untracked/quarantine artifacts before any public-facing cleanup. No files were deleted while preparing this plan.

## Final Untracked-Candidate Decisions

`git status --short` currently shows only untracked artifacts. No tracked source files are dirty. These are the final recommended actions for the remaining candidates; no files were deleted, staged, or committed while preparing this table.

| Path | Final action | Reason |
|---|---|---|
| `.githooks/pre-commit` | Commit later after review | Useful shared hook (`npm run typecheck`), but public hooks should be opt-in and documented in CONTRIBUTING/runbook so contributors are not surprised. |
| `design/extracted/screens/*.jsx`, `design/extracted/styles.css`, `design/extracted/primitives.jsx`, `design/extracted/data.jsx` | Commit later after review | These are the selected source-like design references that match the approved design-source role. Review path mismatches first, especially mover source location. |
| `design/extracted/movers.jsx`, `design/extracted/movers.css`, `design/extracted/movers_data.jsx`, `design/extracted/app.jsx` | Commit later after review | Potentially useful source references, but not all are named in the approved source list; confirm they are current before tracking. |
| `design/second-order-design.zip`, `design/extracted/Second Order.html`, `design/extracted/Second Order-print.html` | Add to `.gitignore` | Generated/export artifacts are public-repo noise and should not be tracked with source references. |
| `docs/superpowers/specs/*.md` | Commit later after review | Some specs contain useful product decisions, but they should be checked for stale V1 wording and normalized into public docs before adding more. |
| `docs/superpowers/plans/*.md` | Delete/quarantine | Mostly local workflow/task planning noise. Extract any durable decisions into normal docs, then keep the raw plans private or delete locally. |
| `scripts/rebuild_archive.py` | Commit later after review | Prior triage found this valuable and that still applies. It defaults to dry-run, but has `--write`; pair it with tests, backup guidance, and runbook warnings before public commit. |
| `tests/test_events_archive_detail_consistency.py` | Commit now | Prior triage found this valuable and that still applies. It is a zero-cost archive read-surface regression test and currently passes in the events discovery suite. |

## Credibility Risks

- Local agent state (`.superpowers/`, `docs/superpowers/**`) can make the repo look like a scratchpad rather than a maintained product. `.superpowers/` is now ignored; `docs/superpowers/**` remains unignored for a future content decision.
- Generated design/export artifacts (`design/*.zip`, exported HTML, root extracted files) blur the line between approved design source and stale generated output.
- Generated eval/report files without context (`eval_run_index.json`, raw calibration/topic reports) can look like unsupported performance claims.
- Operational scripts that can write to the archive (`scripts/rebuild_archive.py`) should not appear without tests, backup guidance, and clear dry-run defaults.
- Empty or duplicate templates (`VALIDATION_LOG.md`) add noise and weaken public documentation focus.

## Design Asset Triage

`design/` currently contains 15 files, about 234 KB total:

- 10 `.jsx` source/reference files
- 2 `.css` files
- 2 exported `.html` files
- 1 `.zip` archive

The README currently points broadly to `repo/design/`, which is directionally correct but too broad for public inclusion. The source-like files under `design/extracted/` match the approved design-reference role. The generated HTML exports and `design/second-order-design.zip` should not be tracked in the public repo.

Recommendation: keep and commit selected design source files only. Do not commit the zip archive or exported HTML. A later design-source commit should either narrow the README reference to the selected committed paths or add a short note explaining that generated exports are intentionally excluded.

## Staged Cleanup Recommendation

1. Done: ignore local-only generated/quarantine state: `.superpowers/`, `gimp/`, root report logs, and `eval_run_index.json`.
2. Next quick commit candidate: `tests/test_events_archive_detail_consistency.py`.
3. Review-before-commit candidates: `.githooks/pre-commit`, selected `design/extracted/` source files, useful `docs/superpowers/specs/*.md`, and `scripts/rebuild_archive.py`.
4. Ignore or quarantine generated design exports: `design/second-order-design.zip` and exported HTML.
5. Quarantine local workflow docs: `docs/superpowers/plans/*.md` after extracting any durable decisions.
