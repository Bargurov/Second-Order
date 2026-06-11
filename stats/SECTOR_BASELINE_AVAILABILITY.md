# Sector-baseline availability

**Date:** 2026-06-11
**Status:** read-only availability/gating report. SPY stays the canonical
abnormal-return benchmark. No events.db / price_cache mutation. No event-study
math change. No sector-relative abnormal return computed. No backfill. No paid
analysis.

Reproduce (the report, not the numbers below, is the source of truth):

```
python scripts/sector_baseline_availability_report.py --db-path events.db --json
python scripts/sector_baseline_availability_report.py --db-path events.db
```

## Why this report exists

The accepted event-study readouts are SPY-relative. A finance reviewer will
ask "vs *what* benchmark, and would a sector comparison even be possible?"
This report answers the **availability** half of that question honestly,
before any readout is changed: for each accepted row, does a *suggested*
sector ETF baseline exist locally and is it **computable at the event date**
for the 1d/5d/20d windows, and what was that sector ETF's **own** raw window
move (descriptive backdrop). It is the gated foundation the O0 memo
recommended — not a new benchmark model.

## SPY canonical stance

SPY remains the single, consistent, broad benchmark behind every abnormal
return; the engine (`BENCHMARK_TICKER = "SPY"`) is untouched. Per-event sector
benchmarks introduce a benchmark-choice degree of freedom, so the sector ETF
here is only a **hint** — never a correction to the SPY readout, and never a
sector-relative abnormal return.

## Sector baseline policy

- **Suggestion source:** the existing
  `scripts/sector_benchmark_suggestion_report._classify` taxonomy, reused
  read-only (direct ticker match → high; one headline sector keyword → medium;
  multiple/none → broad/SPY at low/none, flagged for manual review).
- **Supported sector universe:** XLE, XLF, XLK, XLI, XLB, XLV, XLRE, XLY, XLU
  (+ SPY as the broad fallback).
- **Availability requires a cached, contiguous window** at the event date
  (anchor close at/before the event, a cached close at/after the horizon's
  business-day target, no calendar gap > 5 days) — mirroring the engine's
  contiguity gate. **Cached is not the same as computable-at-date.**

## Availability summary (live snapshot, 2026-06-11; 86 accepted rows)

| metric | value |
|---|---|
| accepted rows | 86 |
| distinct sector suggested | 55 |
| broad/SPY fallback (manual review) | 31 |
| sector window available — 1d | 51 |
| sector window available — 5d | 48 |
| sector window available — 20d | 45 |
| no sector window at any horizon | 35 |

Unavailable reasons (at 20d): broad/SPY fallback (no distinct sector) **31**,
`forward_window_not_cached_20d` **8**, `no_pre_event_close` **2**. The 8 + 2
are the honest C2A signature: the sector ETF is cached, but not with a usable
contiguous window at that event date — surfaced, not assumed and not filled.

So a sector backdrop is locally computable for roughly **half** the accepted
corpus (45–51 of 86 depending on horizon); for the rest it is honestly marked
unavailable.

## N1 walkthrough-case sector context

| case | sector ETF | conf. | 1d | 5d | 20d (ETF's own raw move) |
|---|---|---|---|---|---|
| 1 | XLY | high | available +0.82% | +4.38% | **+10.26%** |
| 61 | SPY | none | — fallback (no distinct sector) | — | — |
| 210 | XLE | high | available −1.92% | −6.20% | **−4.53%** |
| 46 | XLF | medium | unavailable (window not cached for the date) | — | — |
| 66 | XLE | high | available −0.39% | — | **−1.46%** |
| 211 | SPY | none | — fallback (no distinct sector) | — | — |

These are the sector ETF's **own** moves — e.g. energy (XLE) fell ~4.5% over
the 20d window around case 210 — context a SPY-only read does not surface.
They are **not** the named asset's return minus the sector's return.

## Missingness and blocker examples

- **`forward_window_not_cached_20d` (8):** the sector ETF has bars around the
  event but the 20th forward business day is not cached — the window cannot be
  closed yet.
- **`no_pre_event_close` (2):** no cached sector-ETF bar at/before the event
  date — no anchor.
- **`fallback_broad_spy_no_distinct_sector` (31):** the classifier had no
  confident sector (multi-keyword or none), so it fell back to broad/SPY; there
  is no distinct sector to provide context, and the row is flagged for manual
  review.

## What this enables later (and what it does not do now)

These descriptive sector fields are now **embedded into the N1 case
walkthrough** ([`TRANSMISSION_CASE_WALKTHROUGH.md`](TRANSMISSION_CASE_WALKTHROUGH.md))
as a per-case `sector_backdrop` block, beside the canonical SPY readout — a
read-only reuse of this report's `build_report`, still descriptive-only.

That embedding is distinct from the still-**deferred** sector-relative
abnormal-return step: a side-by-side asset-move-vs-SPY and asset-move-vs-sector
comparison, *if* this report shows enough computable coverage (it shows ~half)
and the benchmark-choice disclosure is acceptable. This report deliberately
**does not**:

- change the SPY engine or `BENCHMARK_TICKER`;
- recompute any asset's abnormal return vs a sector ETF;
- backfill or fetch to fill a missing sector window;
- add peer/bespoke baskets.

## Non-claims

- No benchmark replacement: SPY remains the canonical abnormal-return
  benchmark; the sector ETF is a hint, not a correction.
- No event-study math change; the engine and `BENCHMARK_TICKER` are untouched.
- No sector-relative AR/SAR/CAR is computed; the sector move shown is the
  ETF's own raw window change, descriptive only.
- No significance (n=1; no CI, p-value, or FDR); no family-level inference; no
  performance ranking; not a recommendation.
- No paid analysis; no database/price_cache mutation; nothing backfilled or
  fetched. Denominators unchanged: 94 accepted coverage / 86 accepted
  track-record.

## Final recommendation

- **Keep O1 read-only** and use it as the availability map beside the SPY
  event-study layer.
- **Do not change the SPY engine yet.**
- **Only consider O2** (sector-relative abnormal-return comparison) if this
  report's computable coverage (~half the corpus) is judged sufficient and the
  benchmark-choice disclosure is made explicit — and even then as a separate,
  engine-aware, gated task, not a silent benchmark swap.
