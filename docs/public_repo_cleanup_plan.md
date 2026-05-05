# Public Repo Cleanup Plan

Purpose: classify the remaining untracked/quarantine artifacts before any public-facing cleanup. No files were deleted while preparing this plan.

## Current Untracked Set

`git status --short` currently shows only untracked artifacts. No tracked source files are dirty.

| Path | Classification | Public GitHub risk | Recommendation |
|---|---|---|---|
| `.githooks/` | Review for future commit | Low to medium. A repo-managed hook is useful, but an undocumented local hook can surprise contributors. | Either commit with README/runbook setup instructions, or keep local-only and add `.githooks/` to `.gitignore`. |
| `.superpowers/` | Handled: ignored local-only quarantine | High. Contains agent/session state, generated HTML brainstorm output, server PID/state files, and messy workflow traces. | Ignored in `.gitignore`. Safe to delete locally after confirming no active session needs it. Do not commit. |
| `design/` | Keep and commit selected files | Medium. The extracted JSX/CSS source appears to be the current approved design reference, but the zip archive and exported HTML are generated artifacts. | Commit selected source files only: `design/extracted/screens/**`, `design/extracted/styles.css`, `design/extracted/primitives.jsx`, `design/extracted/data.jsx`, and the extracted movers source if still needed. Keep `design/second-order-design.zip` and exported HTML local-only or quarantine/delete later. |
| `gimp/` | Handled: ignored local-only quarantine | High. This is unrelated third-party/agent tooling and would make the repo look unfocused. | Ignored in `.gitignore`. Safe to delete locally unless there is a deliberate image-tooling task later. |
| `CALIBRATION_REPORT.md` | Handled: ignored local-only report artifact | Medium. Useful evidence in principle, but this root-level generated report has mojibake and generated-run flavor. | Ignored in `.gitignore`. Future public calibration notes should be regenerated or polished under `docs/`. |
| `TOPIC_BALANCE_REVIEW.md` | Handled: ignored local-only report artifact | Medium. Useful process material in principle, but this root-level report is detached from current docs and has encoding artifacts. | Ignored in `.gitignore`. Future public topic-balance notes should be cleaned and moved under `docs/`. |
| `VALIDATION_LOG.md` | Handled: ignored local-only scratch log | Medium. Empty duplicate validation template; public repo already has stronger docs. | Ignored in `.gitignore`. Safe to delete locally if superseded by the runbook/checklists. |
| `product_validation_log.md` | Handled: ignored local-only scratch log | Low to medium. It may invite private notes/screenshots if used directly in the repo root. | Ignored in `.gitignore`. If revived publicly, move a cleaned blank template under `docs/`. |
| `eval_run_index.json` | Handled: ignored generated eval artifact | Medium. Generated eval metadata ages quickly and can imply benchmark claims without context. | Ignored in `.gitignore`. Delete local copies after any needed results are summarized. |
| `scripts/rebuild_archive.py` | Review for future commit | Medium. Could be operationally useful, but archive rebuild tooling can mutate data with `--write` and needs tests/docs before public exposure. | Keep unstaged until paired with composer/tests/runbook warnings. Do not ignore as mere scratch yet. |
| `tests/test_events_archive_detail_consistency.py` | Review for future commit | Low. Looks like a serious regression test, but it is broad and untracked. | Run and inspect with current events suite before committing in a dedicated test slice. |
| `docs/superpowers/**` | Review for future commit or move private | Medium to high. These are AI-agent implementation plans/specs with stale V1/task wording and internal workflow instructions. | Extract durable product decisions into normal docs if needed; otherwise keep private/local and ignore the directory. |

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
2. Design-source policy decided: commit selected `design/extracted/` source files only; keep zip/exported HTML local-only or quarantine/delete later.
3. Review public docs candidates: clean and move useful report material into `docs/`, dropping mojibake and stale workflow instructions.
4. Review code/test candidates separately: validate `scripts/rebuild_archive.py` and `tests/test_events_archive_detail_consistency.py` in a focused branch before staging.
5. Still unignored pending future decision: `.githooks/`, `design/`, `docs/superpowers/**`, `scripts/rebuild_archive.py`, and `tests/test_events_archive_detail_consistency.py`.
