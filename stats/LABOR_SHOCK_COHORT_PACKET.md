# Labor-shock cohort packet — UAW auto strike vs SAG-AFTRA media disruption

**Date:** 2026-06-10 · **Status: staged / no-paid review cohort — not accepted
evidence, no promotion, no paid analysis approved.**

Reproduce read-only:

```powershell
python scripts/labor_shock_cohort_packet.py --db-path events.db --json
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged candidates. The labor_inflation family
has **2 staged rows and 0 accepted rows**; both stay outside every accepted
denominator. Cohort scope: included **313 / 314**, nothing deferred.

## Why the labor family matters

Labor shocks are the transmission channel furthest from the archive's
existing coverage (oil/war geopolitics, tariff/sanction policy, antitrust
overhang): a wage-cost / production-disruption mechanism where the *supply
side of the firm itself* is interrupted. The two staged cases carry a
built-in contrast — goods production vs media/content pipeline — that no
other staged family offers.

## Case table (event-date quality from the C4 layer — derived, not assumed)

| id | date | exposed | C4 anchor label | cohort use | subtype |
|---|---|---|---|---|---|
| 313 | 2023-09-15 | GM / F | partial_anticipation | usable_with_caution | production_disruption / wage_cost_pressure |
| 314 | 2023-07-14 | NFLX / WBD | scheduled_or_weak_anchor | **weak_anchor_only** | content_pipeline_disruption / wage_cost_pressure |

313's strike start was partly telegraphed (deadline known; the deal-vs-strike
binary and novel "Stand Up" scope carried the residual surprise). 314's
*order taking effect* is the culmination of an earlier vote — the C4 layer
reads it as a scheduled/weak anchor, so its window measures residual
surprise only.

## Descriptive readout (n=1 per case; AR vs SPY; no significance)

| id | primary | 1d | 5d | 20d |
|---|---|---|---|---|
| 313 | GM | −1.86% | −1.11% | −9.96% |
| 314 | NFLX | +1.49% | −3.91% | −3.77% |

Descriptively: the goods-production case shows a negative drift that deepens
through 20d (consistent with an escalating targeted stoppage, but equally
consistent with 2023-Q3 macro — n=1 cannot separate those). The media case is
flat-to-positive on the weak anchor date and drifts negative later — exactly
the lagged, partly offsetting pipeline mechanism the taxonomy predicts, and
exactly why a weak anchor forbids reading that window as an event effect.

## Goods vs media — mechanism comparison

- **313 (goods):** output stops the day plants strike; finished-vehicle
  inventory buffers the revenue hit; the durable cost is the settlement's
  wage structure. Transmission is *immediate-but-buffered*.
- **314 (media):** production halts but near-term cash costs *fall* (paused
  spend); the revenue impact (release-slate gaps) lands quarters later;
  library depth shields streamers inside the window. Transmission is
  *delayed and partly offsetting*.

This is the comparison's value: the same family label transmits through
different timing and even different signs of near-term cash impact.

## Asset / proxy discipline (local price flags computed live)

| case | category | tickers (local data) |
|---|---|---|
| 313 | direct | GM (yes) · F (yes) |
| 313 | second-order | LEA (yes) · APTV (yes) · BWA (**no**) |
| 313 | context | XLY (yes) · SPY (yes) |
| 313 | excluded | STLA (struck but **not staged on the row**) · TSLA (non-union peer) |
| 314 | direct | NFLX (yes) · WBD (yes) |
| 314 | second-order | DIS (**no**) · PARA (**no**) |
| 314 | context | SPY (yes) |
| 314 | excluded | CMCSA (diversified; channel diluted) |

Notable: the supplier legs **LEA and APTV already have local price data**, so
a future *no-paid* supplier-transmission read of 313 is locally feasible —
unlike the 314 studio legs (DIS/PARA), which would need a cache backfill.

## How C4 changes interpretation

Labels are consumed from `scripts/event_date_quality_report.py` at run time —
if a row's wording or collisions drift, the packet's labels and cohort_use
move with it. The inherited rules: 314's window is residual-surprise only;
313's 1d read may understate (or misplace) repricing that leaked in before
the deadline.

## Case and family limits

- 313: targeted (not full) stoppage mutes the output shock; inventory
  buffers push margin impact past 20d; supplier legs not staged.
- 314: weak anchor; offsetting near-term cash effects; library depth.
- Family: two cases is a contrast, not a cohort — different sectors,
  different anchor quality, different 2023 macro windows. No pooled number
  is computed and none would be defensible.

## Non-claims

- Staged candidates are not accepted evidence; denominators (94 / 86)
  unchanged; no promotion, no stage or hygiene change.
- No paid analysis run or approved; paid `/analyze` remains blocked.
- Descriptive n=1 readouts only — no CI, p-value, FDR, or significance; no
  family-level inference; no labor-shock edge claim of any kind.
- Mechanism chains and subtypes are research taxonomy to be tested; the
  closed Phase 1 / Phase 2 FDR pools are untouched.

## Final disposition

- **313** — useful for future no-paid review **with the partial-anticipation
  caveat**; the locally-feasible supplier read (LEA/APTV) is the natural
  next no-paid step if the family is ever expanded.
- **314** — useful **only as a weak-anchor case**: its window must be read as
  residual surprise, not an event effect, unless later local evidence
  re-dates the information shock.
- **No paid analysis approved; no promotion authorized.** Future work on
  this family stays no-paid unless a later, separately-approved gate says
  otherwise.
