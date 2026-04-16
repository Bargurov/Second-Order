# Sector Uncertainty — Design Spec
**Date:** 2026-04-16
**Status:** Approved

## Problem

The product already tracks two uncertainty signals but presents them inconsistently:

- **Vol-based sector uncertainty** (`sector_uncertainty` in `/stress`): 12 sector ETFs, 20d realized vol vs SPY baseline — surfaced as a secondary bottom row in the StressStrip, only when concentration ≥ "mixed".
- **News-derived sector uncertainty** (`uncertainty_concentration.py`): scores sectors by news cluster density and high-uncertainty fraction — **not surfaced in the UI at all**.

The global stress regime (5 signals) always leads visually regardless of how concentrated sector uncertainty actually is. When a clear sector is driving uncertainty, the UI buries the signal.

## Goal

Surface sector-specific uncertainty in the `UncertaintySection` of Market Overview:
- Lead with sector concentration when it is clear (news-first signal)
- Use vol-based data as corroboration per sector chip
- Fall back to global uncertainty display when broad/diffuse
- Keep the existing global context visible as a baseline at all times

---

## Approach: Extend `/market-context` + inject into existing data flow

No new endpoint. No extra frontend fetch. The market context endpoint is already a composition layer — we add one more field to it.

---

## Section 1 — Backend & Data

**File:** `routes/market.py` (or wherever `compose_market_context` is called)

Steps:
1. Fetch recent clusters using the existing cluster store access (last 24h clusters, same window used elsewhere in the route)
2. Call `compute_uncertainty_concentration(clusters)` from `uncertainty_concentration.py` — pure Python, no I/O
3. Attach result as `uncertainty_concentration` in the market context response

**Shape added to `/market-context` response:**
```python
"uncertainty_concentration": {
    "uncertainty_scope": "global" | "sector" | "mixed",
    "sector_uncertainty": [
        { "sector": str, "score": int, "cluster_count": int, "high_fraction": float }
    ],
    "lead_sector": str | None
}
```

No new endpoint. Cached with the existing market-context stale/refetch cycle.

---

## Section 2 — Frontend Types & Data Layer

**File:** `frontend/src/lib/api.ts`

Add types:
```typescript
interface SectorUncertaintyEntry {
  sector: string
  score: number
  cluster_count: number
  high_fraction: number
}

interface UncertaintyConcentration {
  uncertainty_scope: "global" | "sector" | "mixed"
  sector_uncertainty: SectorUncertaintyEntry[]
  lead_sector: string | null
}
```

Add to `MarketContext`:
```typescript
uncertainty_concentration?: UncertaintyConcentration
```

No new query keys or hooks. `useMarketContext()` already fetches this endpoint.

**Vol corroboration mapping (in component):**
For each news-derived sector entry, look up a matching entry in `stress.sector_uncertainty?.sectors` by sector name. If found and `vol_ratio ≥ 1.3`, attach the multiplier badge. If not found or calm, no badge.

---

## Section 3 — UncertaintySection Restructure

**File:** `frontend/src/components/pages/market-overview.tsx`

The `UncertaintySection` gets conditional rendering based on `uncertainty_scope`.

### When `uncertainty_scope === "sector"` (concentration is clear)

- **Header:** Lead sector name as primary label instead of global regime string
  - e.g., "Energy · Sector Concentration" instead of "Geopolitical Undercurrent"
- **Primary row:** Up to 3 sector chips (top scorers from news-derived data)
  - Each chip: sector name + score dot (`high_fraction > 0.5` → coral/stressed color; otherwise muted gray) + vol_ratio badge if corroborated (`1.56×` in muted teal, only when `vol_ratio ≥ 1.3`)
- **Secondary (below):** Existing 5-signal grid at `opacity-50`, with a quiet "Baseline" metadata label above it (only shown in sector-lead mode)
  - Global context remains visible — just not the lead

### When `uncertainty_scope === "global"` | `"mixed"` | absent

- Render exactly as today — no visual change. Global regime badge leads, sector pressure row at bottom if stress is concentrated.

### Compact rules

- Max 3 sector chips in the lead row
- No new surface levels or colors — sector chips reuse existing pill style from the current Sector Pressure Row
- Vol badge reuses existing `×` multiplier style
- "Baseline" label for de-emphasized signal grid is quiet metadata text, not a new heading

---

## What is NOT changing

- The `/stress` endpoint — untouched
- `stress-strip.tsx` — untouched (used on analysis page)
- `market-backdrop-strip.tsx` — untouched
- All other market overview sections
- Backend analysis pipeline

---

## Files to touch

| File | Change |
|------|--------|
| `routes/market.py` | Add `uncertainty_concentration` to market context composition |
| `uncertainty_concentration.py` | Verify function signature; no logic changes expected |
| `frontend/src/lib/api.ts` | Add `UncertaintyConcentration` types + field to `MarketContext` |
| `frontend/src/components/pages/market-overview.tsx` | Restructure `UncertaintySection` with conditional lead logic |

---

## Edge Cases

- **`uncertainty_concentration` unavailable** (clusters empty or fetch fails): fall back to global display — same as `uncertainty_scope === "global"`
- **Lead sector has no vol corroboration** (sector not in stress.sector_uncertainty or vol_ratio < 1.3): show chip without badge — news signal alone is sufficient to lead
- **`uncertainty_scope === "mixed"`**: render as global (today's behavior) — mixed signals don't warrant a sector lead
