# Mechanism-family research overview

**Date:** 2026-06-10 · **Scope:** read-only research-coverage map; not evidence,
not promotion, no paid analysis.

Second Order organizes events into a **mechanism-family taxonomy** — the
canonical registry in `mechanism_family.py` (`FAMILY_VALIDATION_MATRIX`) defines
14 families (tariff, sanction, supply_shock, ceasefire_deescalation,
policy_surprise, fiscal_issuance, labor_inflation, bank_stress,
commodity_squeeze, supply_normalization, external_balance, regulation,
industrial_policy, none), each with expected channels, timings, and
invalidation templates. A family label is a research taxonomy entry — **not
causal proof** — and most of the taxonomy currently has little or no accepted
data. This note maps which families carry accepted evidence, which exist only
as staged no-paid candidates, and how the Tier-1 shortlist would broaden the
archive if later reviewed.

Recompute everything here read-only:

```powershell
python scripts/mechanism_family_overview_report.py --db-path events.db --json
```

## Family coverage (live snapshot, 2026-06-10)

Denominators: **180** archive rows · **94** accepted coverage · **86** accepted
track-record · **13** staged candidates (excluded: 71 synthetic_seed ·
1 curated_intake · 1 analysis_pending_review).

| family | status | accepted | (curated obs) | staged | accepted compute-ready |
|---|---|---|---|---|---|
| tariff | accepted evidence present | 4 | 4 | 0 | 4 |
| sanction | accepted evidence present | 4 | 4 | 4 | 4 |
| policy_surprise | excluded-only (1 intake stub) | 0 | 0 | 0 | 0 |
| regulation | **staged only** | 0 | 0 | 5 | 0 |
| labor_inflation | **staged only** | 0 | 0 | 2 | 0 |
| industrial_policy | **staged only** | 0 | 0 | 2 | 0 |
| none (untagged) | **limitation bucket** | 86 | 0 | 0 | 70 |

`accepted compute-ready` is scoped only to accepted-corpus rows and sums to
the canonical accepted compute-ready count of 78. Staged candidate event-study
availability is handled by the queue and shortlist reports; it is not merged
into this accepted count or any accepted denominator.

Accepted evidence and staged candidates are **strictly separated**: the
accepted lens is the canonical hygiene-aware corpus (excludes non-analysis
stages and `event_hygiene` synthetic-seed rows — the same denominator as
`scripts/event_study_coverage_report.py`), and staged `z1a_candidate_pack` rows
never enter any accepted denominator.

Two structural facts a reviewer should read directly off this table:

1. **Every family-labeled accepted row is a curated observation** (the eight
   Phase-K tariff/sanction rows). Observations carry no LLM thesis, so they
   contribute to coverage but not to the track record.
2. **Every thesis-outcome row (the 86-row track-record corpus) is untagged**
   (`none`). Per-family track-record splits are therefore structurally
   degenerate today — a data limitation this project states rather than hides.
   A read-only overlay now measures this limitation's shape with
   deterministic headline rules (no DB write, no inference):
   [`stats/ACCEPTED_FAMILY_OVERLAY.md`](ACCEPTED_FAMILY_OVERLAY.md) /
   `scripts/accepted_family_overlay_report.py`.

## Tier-1 shortlist bridge (staged / no-paid only)

The committed decision log `stats/STAGED_CANDIDATE_SHORTLIST.md` (AX1–AX5)
keeps three staged candidates at Tier 1 for future no-paid/human review. All
three remain **staged candidates — not accepted evidence, not approved for paid
analysis**:

- **#303 — DOJ v Apple (2024-03-21, AAPL, regulation):** conduct-remedy
  antitrust on a discrete suit-filing date; the regulation family has zero
  accepted rows.
- **#304 — DOJ v Google ad-tech (2023-01-24, GOOGL, regulation):**
  structural-remedy / divestiture antitrust; pairs with 303 as a
  conduct-vs-structural contrast within the same new family. A read-only
  paid-gate packet (still no-paid, blocked by default) is at
  [`stats/CANDIDATE_304_PAID_GATE_PACKET.md`](CANDIDATE_304_PAID_GATE_PACKET.md).
- **#313 — UAW Stand Up Strike (2023-09-15, GM/F, labor_inflation):**
  production-disruption / wage-cost shock; the labor family has zero accepted
  rows and sits furthest from the archive's existing concentration.

If later reviewed, these would take the archive's family coverage from two
accepted families (tariff, sanction — both curated-observation-only, both
policy/trade-flavored) toward antitrust-regulation and labor mechanisms —
broadening the research base beyond the oil / war / semiconductor cluster the
archive and curated anchors currently emphasize. The remaining staged
semiconductor-export candidates (308/309/310) are deliberately deferred as
near-siblings of existing curated anchors; see the shortlist note.

Event-date anchor quality for every row above (clean filing vs scheduled
signing vs thread sibling vs duplicate) is classified read-only in
[`stats/EVENT_DATE_QUALITY.md`](EVENT_DATE_QUALITY.md) /
`scripts/event_date_quality_report.py` — read it before interpreting any
1d/5d/20d window. The staged regulation cases are compared as a family
(taxonomy, anchors, descriptive readouts, still no-paid) in
[`stats/REGULATION_COHORT_PACKET.md`](REGULATION_COHORT_PACKET.md) /
`scripts/regulation_cohort_packet.py`; the staged labor cases (UAW goods
strike vs SAG-AFTRA media pipeline) likewise in
[`stats/LABOR_SHOCK_COHORT_PACKET.md`](LABOR_SHOCK_COHORT_PACKET.md) /
`scripts/labor_shock_cohort_packet.py`. The cross-family consolidation —
anchor quality, packet coverage, computability, and ranked no-paid next
moves over all 13 staged candidates — is
[`stats/STAGED_FAMILY_COVERAGE.md`](STAGED_FAMILY_COVERAGE.md) /
`scripts/staged_family_coverage_report.py`.

## Limitations and non-claims

- Many accepted rows (86 of 94) remain untagged (`none`); family-level
  analysis does not yet cover the thesis corpus. A read-only overlay
  ([`ACCEPTED_FAMILY_OVERLAY.md`](ACCEPTED_FAMILY_OVERLAY.md)) and its
  weak-bucket diagnostic
  ([`ACCEPTED_FAMILY_OVERLAY_REVIEW.md`](ACCEPTED_FAMILY_OVERLAY_REVIEW.md)),
  plus a mechanism-text second lens
  ([`ACCEPTED_FAMILY_SECOND_LENS.md`](ACCEPTED_FAMILY_SECOND_LENS.md)),
  classify those rows in memory without writing labels.
- Staged candidates are review staging, **not evidence**, and never enter
  accepted denominators.
- Representative cases are **illustrative, not proof** of any mechanism.
- No paid analysis was performed; paid `/analyze` remains blocked; no
  candidate was promoted and no stage or hygiene flag was changed.
- No single-event significance is claimed (n=1: no CI, p-value, or FDR).
- The closed Phase 1 / Phase 2 FDR pools are untouched and separate.
