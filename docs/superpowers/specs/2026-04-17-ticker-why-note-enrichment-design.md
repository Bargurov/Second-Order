# Ticker Why-Note Enrichment

**Date:** 2026-04-17
**Status:** Approved

## Summary

Enrich the "Why it matters" note in `TickerDetailPanel` so it reflects the event's causal channel (shock type, policy sensitivity, or mechanism) rather than a generic beneficiary/loser label. Also surface the note in the Market Movers panel, where it is currently absent.

## Background

`TickerDetailPanel` already has a `why` slot driven by `AnalysisExtra.why`. In the analysis view it is populated by `_buildWhyNote()`, which does a shallow symbol lookup in the `beneficiaries`/`losers` arrays and falls back to a truncated `mechanism_summary` with a generic prefix. In Market Movers the panel is rendered without `extra`, so the `why` block never appears.

`AnalysisDetail` already carries `shock_decomposition` and `policy_sensitivity` — enough to build a causally grounded note with no backend changes.

## Note Construction — Three-Tier Priority Chain

### Tier 1: Shock-anchored (primary)

**Condition:** `shock_decomposition.primary_label` is present.

**Format:**
```
"{primary_label} — {role_connector} {channel_fragment}"
```

- `role_connector`:
  - `"beneficiary through"` when `ticker.role === "beneficiary"`
  - `"exposed via"` otherwise
- `channel_fragment`: `shock_decomposition.rationale` if present; else `mechanism_summary`. Truncated to 80 chars with `…`.

**Examples:**
```
Supply Shock — exposed via input-cost pass-through across semiconductor supply chains
Demand Shock — beneficiary through pricing power and order-flow re-routing
```

### Tier 2: Policy-sensitive (secondary)

**Condition:** `policy_sensitivity.stance` is `"reinforced"` or `"fighting"` AND `policy_sensitivity.explanation` is present AND no shock label from Tier 1.

**Format:**
```
"Policy headwind — {explanation}"      // stance === "fighting"
"Policy-sensitive — {explanation}"     // stance === "reinforced"
```

`explanation` truncated to 100 chars with `…`.

Stance `"neutral"` is skipped — not informative enough to surface.

### Tier 3: Mechanism fallback

**Condition:** Neither Tier 1 nor Tier 2 applies.

**Format:**
```
"Beneficiary — {mechanism_summary}"
"Exposed to downside — {mechanism_summary}"
```

`mechanism_summary` truncated to 110 chars with `…`. This replaces the current "Identified as beneficiary" and "Exposed to downside" prefixes — same data, cleaner labels.

## Market Movers Note

`MarketMover` carries `mechanism_summary` and each `MoverTicker` has `role`. No shock/policy fields are present, so only the Tier 3 pattern applies. The note is computed inline in `market-movers.tsx` at the `TickerDetailPanel` call site.

```
"Beneficiary — {mechanism_summary_truncated_110}"
"Exposed to downside — {mechanism_summary_truncated_110}"
```

## Files Changed

| File | Action | Change |
|------|--------|--------|
| `frontend/src/components/ui/ticker-detail-panel.tsx` | Modify | Add `why?: string` to `MoverExtra`; render why block from `extra?.why ?? moverExtra?.why` |
| `frontend/src/components/pages/analysis-view.tsx` | Modify | Replace `_buildWhyNote()` body with three-tier chain |
| `frontend/src/components/pages/market-movers.tsx` | Modify | Compute `whyNote` inline and pass as `moverExtra.why` |

**Not changed:** all backend files, DB schema, API routes, query keys, existing `TickerDetailPanel` props contract.

## Rendering

The why block in `TickerDetailPanel` renders when `extra?.why || moverExtra?.why` is truthy. Layout, label ("Why it matters"), and typography are unchanged.

## Verification

No frontend test framework exists in this project. `_buildWhyNote()` is a pure function with no side effects; extract and verify each tier by running the dev server and opening a saved event with:

- A known supply/demand shock → confirm Tier 1 note
- A policy-sensitive event (stance reinforced/fighting) with no shock → confirm Tier 2 note
- An event with neither → confirm Tier 3 fallback
- A market mover card → confirm the note appears where it previously showed nothing
