# Sanction/export-control thread collapse — 307–310 vs curated 298/300/301

**Date:** 2026-06-11 · **Status: staged / no-paid — nothing here is accepted
evidence, no promotion, no paid analysis approved.**

Reproduce read-only:

```powershell
python scripts/sanction_thread_collapse_report.py --db-path events.db --json
```

## The headline (honest breadth accounting)

| raw staged rows | rows adding independent events | effective threads |
|---|---|---|
| **4** (307/308/309/310) | **0** | **2** |

Connected components over the C4 thread links: **[298, 309]** (the Huawei
thread) and **[300, 307, 308, 310]** (the NVIDIA / advanced-computing
thread). Every staged sanction row collapses into a component **rooted at a
curated anchor** — the staged rows add thread depth and escalation context,
never independent events. Counting them as four pieces of evidence would
multiply one observation into four.

Denominators unchanged: 180 archive rows · 94 accepted coverage · 86 accepted
track-record · 13 staged.

## Thread membership (derived from the C4 layer, not asserted)

| id | date | exposed | anchors | what it adds (and does not) |
|---|---|---|---|---|
| 307 | 2022-10-07 | NVDA/AMD | 300 | industry-wide instrument + AMD leg — thread evolution, not a new thread |
| 308 | 2023-10-17 | NVDA/AMAT | 300, 307 | equipment-scope tightening — least new information in the cluster |
| 309 | 2020-05-15 | QCOM/SMH | 298 | FDPR instrument detail inside the Huawei thread |
| 310 | 2025-04-15 | NVDA/AMD | 300, 307, 308 | a quantified company-disclosed charge — magnitude context, same thread |

Related curated anchors: **298** (Huawei Entity List, mechanical link),
**300** (NVIDIA license, mechanical link), **301** (SMIC/equipment — curated
context per the AX1 review; no mechanical link fires, and the label says so).
All three are clean discrete anchors per C4.

## Descriptive readouts (n=1, thread-caveated)

| id | primary | 1d | 5d | 20d |
|---|---|---|---|---|
| 307 | NVDA | −2.60% | −5.61% | +13.49% |
| 308 | NVDA | −2.63% | +2.22% | +10.10% |
| 310 | NVDA | −4.65% | −8.05% | +11.33% |
| 309 | QCOM | +2.46% | +0.67% | +6.76% |

The three NVDA rows are the caveat made visible: negative 1d, **+10–13% 20d,
three times, on the same ticker** — overlapping windows riding one secular
NVDA tape. Reading these as three confirmations would be the precise error
this report exists to prevent.

## How to treat 307–310 in future packets

Collapse to thread level: at most **one observation per thread component**,
anchored at the curated root (298 or 300), with the staged rows as dated
escalation context. Only build a sanction/export-control family packet after
independent anchors are separated from the thread — none exist among the
staged rows today.

## How this updates C3

C3's rank-4 no-paid move is done. The coverage board's "sanction staged 4"
must be read through this collapse: **effective new evidence contribution =
0 independent events** (the family's accepted evidence remains the curated
observations). The board's caution ("thread-dense, not independent breadth")
is now quantified.

## Disposition

- **Collapse/defer 307–310** (`collapse_or_defer_ids: [307, 308, 309, 310]`);
  keep staged/no-paid unless a row is later shown independent (the report
  re-derives membership from C4 each run — a row that stops reading as a
  sibling surfaces as `review_as_potential_independent_event`).
- **No paid analysis; no promotion.**

## Non-claims

- Staged candidates are not accepted evidence; thread siblings are not
  independent breadth; denominators (94/86) unchanged.
- No paid analysis run or approved; paid `/analyze` remains blocked; no
  promotion, no stage/hygiene change.
- Descriptive n=1 readouts only — no CI, p-value, FDR, or significance; no
  family-level inference; not a recommendation.
- The closed Phase 1 / Phase 2 FDR pools are untouched.
