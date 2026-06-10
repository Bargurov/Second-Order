# Staged-candidate shortlist — no-paid review log (AX1–AX4)

**Date:** 2026-06-10 · **Scope:** read-only, no-paid decision log.

This note preserves the AX1–AX4 no-paid review decisions for the staged
`z1a_candidate_pack` queue so the shortlist is not trapped in chat memory. **It
is a no-paid, read-only shortlist — not a promotion, not approval for paid
analysis, and not evidence.** Staged candidates are excluded from every
accepted-corpus denominator; this is review staging only. Paid `/analyze`
remains blocked.

## Baseline (at time of review)
- main / origin/main expected at **`4dab1a1`**.
- live `events.db` SHA-256 expected **`AE3A1187…`** (unchanged across AX1–AX5).
- Queue counts (via `scripts/research_queue_report.py`, read-only):
  **13 staged · 12 `ready_for_no_paid_review` · 1 `defer_near_duplicate`** (302).

## Tier table
| Tier | Candidates | Note |
|---|---|---|
| **Tier 1** (best next no-paid/human review) | **303** Apple antitrust · **304** Google ad-tech · **313** UAW strike | discrete-date, new mechanism families, diversify the archive |
| **Tier 2** (keep staged, lower priority) | 305 Live Nation · 306 Visa · 307 BIS broad export rule (2022) · 311 CHIPS Act · 312 IRA · 314 SAG-AFTRA | valid but family-redundant (305/306/314), thread-clustering (307), or weak event-date anchor (311/312) |
| **Tier 3 / defer** | 302 FTC Amazon · 308 BIS strengthening (2023) · 309 Huawei FDPR (2020) · 310 NVIDIA H20 (2025) | duplicate (302) or semiconductor-thread siblings of existing curated rows |

Candidate reference (id · date · ticker / family):
302 2023-09-26 AMZN/regulation · 303 2024-03-21 AAPL/regulation · 304 2023-01-24
GOOGL/regulation · 305 2024-05-23 LYV/regulation · 306 2024-09-24 V/regulation ·
307 2022-10-07 NVDA/sanction · 308 2023-10-17 NVDA/sanction · 309 2020-05-15
QCOM/sanction · 310 2025-04-15 NVDA/sanction · 311 2022-08-09 INTC/industrial_policy ·
312 2022-08-16 FSLR/industrial_policy · 313 2023-09-15 GM/labor_inflation ·
314 2023-07-14 NFLX/labor_inflation.

## Special decisions
- **302 vs row 315:** 302 (FTC v Amazon) is a near-duplicate of the **quarantined**
  row 315 (same announcement, date 2023-09-26, AMZN; 315 stays
  `analysis_pending_review`). **Keep 302 staged but deferred, and retire it from
  future paid consideration** — paying to analyze it would duplicate an event
  already in the archive. Denominator impact: zero (both already excluded). Row
  315's own disposition is the operator's call, out of scope here.
- **307 vs curated row 300:** distinct events (307 = the broad Oct-2022 BIS rule,
  NVDA+AMD; 300 = the Aug-2022 NVIDIA-specific license, curated). The mechanical
  collision correctly does not fire — 307 is **not** a duplicate — but it adds to
  the same 2022 US-China semiconductor export-control density. **Keep 307 staged
  but Tier 2.**
- **308 / 309 / 310 are semiconductor-thread siblings of existing curated anchors**
  (308 ↔ curated 301 SMIC/equipment; 309 ↔ curated 298 Huawei; 310 ↔ curated 300
  NVIDIA license). **Defer** — they densify an already-curated thread rather than
  broaden the archive.

## Tier 1 rationale
- **303 — DOJ v Apple (2024-03-21, AAPL, regulation):** discrete suit-filing date;
  conduct-remedy antitrust (iPhone developer restrictions, Sherman §2). New
  `regulation` family (0 in the accepted archive). Single-name; thin second-order.
- **304 — DOJ v Google ad-tech (2023-01-24, GOOGL, regulation):** discrete
  suit-filing date; structural-remedy / divestiture antitrust (the ad-tech stack).
  Pairs with 303 as a conduct-vs-structural contrast; latent ad-tech ecosystem
  second-order.
- **313 — UAW Stand Up Strike begins (2023-09-15, GM/F, labor_inflation):**
  strike-start production-disruption + wage-cost shock. New `labor_inflation`
  family; the most diversifying Tier-1 candidate. Honest caveats: the strike
  deadline was partly anticipated, and supplier second-order names are not yet
  staged.

## Non-claims
- No paid analysis was performed; paid `/analyze` remains blocked.
- No DB mutation, no stage change, no promotion, no `event_hygiene` change.
- These are n=1 case reviews — **not proof**, and no single-event significance is
  claimed.
- Any event-study readouts referenced during review are **descriptive only**
  (the reports recompute them read-only); they did not rank the candidates —
  tiering is by research design (mechanism distinctness, family diversity,
  event-date discreteness, falsifier clarity).
- This shortlist is separate from the closed Phase 1 / Phase 2 FDR pools.

## Next recommended action
Review the **Tier 1 shortlist (303, 304, 313)** as no-paid / human candidates
before any paid consideration. After the Tier-1 trio, the cleanest next is 314
(services-sector labor contrast to 313); 311/312 add the `industrial_policy`
family but carry the anticipated-signing weak-date caveat. **Do not continue
queue churn** unless there is a specific reason; do not paid-analyze any
candidate without explicit approval and a fresh backup.
