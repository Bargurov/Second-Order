# Industrial-policy anchor-quality packet — 311 (CHIPS) / 312 (IRA)

**Date:** 2026-06-11 · **Status: staged / no-paid — both cases stay
`z1a_candidate_pack`; no promotion, no paid analysis approved.**

Reproduce read-only:

```powershell
python scripts/industrial_policy_anchor_packet.py --db-path events.db --json
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged. industrial_policy: **2 staged, 0
accepted**. Both cases need re-anchoring (`reanchor_needed_ids: [311, 312]`).

## Why this family matters — and why its anchors don't (yet)

Industrial policy would add a *beneficiary* channel (subsidies raising
specific firms' economics) — different from every other staged family. But
both cases anchor on **bill signings**: the scheduled end of a months-long
public legislative path. The market prices a package as its text, votes, and
compromises resolve; the C4 layer reads both dates as
`scheduled_or_weak_anchor` (anticipation risk: high), so their windows
measure **residual surprise only**.

## Cases (labels from the C4 layer — derived, not assumed)

| id | date | exposed | C4 label | subtype |
|---|---|---|---|---|
| 311 | 2022-08-09 | INTC / MU | scheduled_or_weak_anchor | semiconductor capacity subsidy / supply-chain resilience |
| 312 | 2022-08-16 | FSLR / ENPH | scheduled_or_weak_anchor | clean-energy tax credit / manufacturing subsidy |

## Descriptive readout (n=1, AR vs SPY) — and the cautionary exhibit

| id | primary | 1d | 5d | 20d |
|---|---|---|---|---|
| 311 | INTC | +0.36% | +0.38% | −7.91% |
| 312 | FSLR | +0.12% | +1.84% | **+24.21%** |

Both 1d windows are near zero — exactly what a priced-in signing predicts.
FSLR's +24% 20d drift is the **cautionary exhibit**: on a weak anchor it must
NOT be read as a signing-date event effect. It is descriptive post-passage
repricing context whose information arrived along the legislative path (and
in the broader tape), not on the ceremony date. 311's −7.9% INTC drift cuts
the *opposite* way despite the same "beneficiary" framing — single names
carry idiosyncratic loads that swamp residual policy surprise.

## What alternative anchors would be needed

1. First material bill text / subsidy-design disclosure.
2. Major vote or passage surprise (cloture / floor outcome, surprise
   compromise).
3. Conference/compromise change that altered scope or beneficiaries.
4. Final signing **only** if the signing itself changed uncertainty.

## Local evidence — present vs missing (computed, not asserted)

- **Present:** deep pre-signing price history for all four exposed tickers
  (INTC/MU **276** and FSLR/ENPH **277** cached pre-signing dates). If better
  anchor dates were identified, **re-anchored windows would be computable
  today without any cache backfill** — the opposite of the labor supplier
  gap (C2A).
- **Missing:** **no archive event rows exist for any pre-signing milestone**
  — no vote, passage, or design-disclosure anchor is locally representable.
  Identifying candidate dates needs a read-only timeline task; ingesting
  them as anchors would be **separately-gated curated intake**, not part of
  any read-only work.

## Disposition

- **Keep 311/312 staged/no-paid.** Current windows read as residual surprise
  only; the family must not be presented as clean evidence.
- **Do not spend paid analysis; do not promote.**
- **Re-anchor only if** a later read-only timeline task (D2) identifies
  better local anchor dates — feasibility is split: price-side ready,
  event-row-side missing.

## How this updates C3

C3 ranked this review as the top no-paid move. The answer: the family stays
weak at its current anchors, but the **re-anchor path is cheaper than
assumed** — no price backfill is needed, only milestone event rows (a gated
intake decision, with date identification doable read-only first).

## Non-claims

- Staged candidates are not accepted evidence; denominators (94/86)
  unchanged; no promotion, no stage/hygiene change.
- No paid analysis run or approved; paid `/analyze` remains blocked.
- Descriptive n=1 readouts only — no CI, p-value, FDR, or significance; no
  family-level inference; not a recommendation.
- A signing date is never treated as clean policy discovery here.
- The closed Phase 1 / Phase 2 FDR pools are untouched.
