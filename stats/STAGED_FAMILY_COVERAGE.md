# Staged-family coverage board — cross-family research view

**Date:** 2026-06-11 · **Scope: the staged/no-paid universe only — nothing
here is accepted evidence, no promotion, no paid analysis approved.**

Reproduce read-only:

```powershell
python scripts/staged_family_coverage_report.py --db-path events.db --json
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged candidates (71 synthetic seeds + 1
intake stub excluded and disclosed). Everything below is review staging.

## Family coverage (live snapshot)

| family | staged | accepted | packet | clean | partial | weak | thread | dup | primary legs computable |
|---|---|---|---|---|---|---|---|---|---|
| regulation | 5 | 0 | **available** (C1) | 4 | 0 | 0 | 0 | 1 | 5/5 |
| labor_inflation | 2 | 0 | **available** (C2 + C2A slice) | 0 | 1 | 1 | 0 | 0 | 2/2 |
| industrial_policy | 2 | 0 | none yet | 0 | 0 | 2 | 0 | 0 | 2/2 |
| sanction (export-control) | 4 | 4 (curated obs) | none yet | 0 | 0 | 0 | 4 | 0 | 4/4 |

Anchor labels come from the C4 event-date quality layer at run time; packet
status is detected from the committed artifacts on disk; computability is the
event-study gate per staged primary leg.

## Case board (dispositions)

| id | family | anchor label | disposition |
|---|---|---|---|
| 302 | regulation | duplicate_or_deferred | deferred duplicate (vs quarantined 315); retired from paid |
| 303 | regulation | clean | clean anchor (Tier 1) |
| 304 | regulation | clean | clean anchor (Tier 1); **paid path closed-deferred by operator** |
| 305 | regulation | clean | clean anchor (Tier 2 priority) |
| 306 | regulation | clean | clean anchor (Tier 2 priority) |
| 307–310 | sanction | thread sibling | not independent breadth — collapse into the export-control thread (curated anchors 298/300/301) or defer |
| 311 / 312 | industrial_policy | scheduled/weak | residual surprise only — **must not be read as clean evidence** |
| 313 | labor | partial anticipation | usable with caveat (Tier 1); C2A deep slice exists |
| 314 | labor | scheduled/weak | weak anchor only |

## Computability caveats (the C2A lesson, kept visible)

Rows cached is **not** computable-at-date. All 13 staged primary legs compute
locally today; the only failures are transmission legs:

- **313 supplier legs LEA / APTV: rows cached (2026-only), 0 pre-event dates
  for 2023-09-15 — not computable** without a bounded (~85-bar) pre-event
  backfill that would need its own approval gate.

## Deep slices that exist

- `stats/REGULATION_COHORT_PACKET.md` — antitrust family packet (C1).
- `stats/LABOR_SHOCK_COHORT_PACKET.md` — goods-vs-media labor packet (C2).
- `stats/UAW_SUPPLIER_TRANSMISSION_PACKET.md` — 313 deep slice; corrected the
  supplier-computability assumption (C2A).

## What each family adds — and lacks

- **regulation:** adds legal-overhang transmission with a conduct-vs-
  structural contrast; lacks second-order ecosystem data and a paid path
  (304 deferred).
- **labor_inflation:** adds wage-cost/production-disruption transmission with
  a goods-vs-services contrast; lacks supplier pre-event history and carries
  anchor caveats on both cases.
- **industrial_policy:** would add a beneficiary channel; lacks any clean
  anchor — both cases sit on scheduled signings.
- **sanction staged rows:** add depth on the existing export-control thread;
  they do **not** add independent family breadth.

## Ranked no-paid next moves

1. **industrial_policy anchor-quality / policy-timeline review** (311/312):
   find the genuine information-shock dates inside each bill's path before
   reading any window. Read-only. — **DONE (D1):** see
   [`stats/INDUSTRIAL_POLICY_ANCHOR_PACKET.md`](INDUSTRIAL_POLICY_ANCHOR_PACKET.md);
   verdict: keep staged/deferred, re-anchor path is price-side ready but
   milestone event rows are missing locally.
2. **Regulation conduct-vs-structural comparison memo** over clean anchors
   303/304; cautious Tier-2 review of 305/306 after. Read-only. — **DONE
   (F1):** see
   [`stats/REGULATION_CONDUCT_VS_STRUCTURAL.md`](REGULATION_CONDUCT_VS_STRUCTURAL.md);
   key point: 304's stronger negative readout is confounded with exposure
   share and does not establish mechanism strength.
3. **Design the bounded LEA/APTV pre-event backfill** for the 313 supplier
   read (~85 bars each around 2023-09-15) — *the backfill writes price_cache
   and requires its own approval gate.*
4. **Thread-collapse note** grouping 307–310 with curated anchors 298/300/301
   as one export-control thread. Read-only. — **DONE (E1):** see
   [`stats/SANCTION_THREAD_COLLAPSE.md`](SANCTION_THREAD_COLLAPSE.md);
   verdict: raw 4 staged rows → **0 independent events**, 2 effective threads
   ([298, 309] and [300, 307, 308, 310]); collapse/defer all four.

## Non-claims

- Staged candidates are not accepted evidence; denominators (94/86)
  unchanged; no promotion, no stage/hygiene change.
- No paid analysis run or approved anywhere on this board; paid `/analyze`
  remains blocked; 304's paid path stays closed-deferred.
- Underlying windows are descriptive n=1 point estimates — no CI, p-value,
  FDR, or significance; the board is a research index, not family-level
  inference and not a recommendation.
- Dispositions and rankings are review ordering, revisable; the closed
  Phase 1 / Phase 2 FDR pools are untouched.

## Final disposition

Regulation and labor now have real family packets, and labor has one deeper
313 slice that corrected the supplier-computability assumption.
Industrial_policy must not be read as clean evidence yet; the staged
sanction rows are thread-dense and must not be treated as independent
breadth. **No paid analysis is approved.**
