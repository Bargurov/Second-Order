# Transmission Chain Redesign — Design Spec
**Date:** 2026-04-15

## Problem

The existing `TransmissionChain` component renders each step as a large 80px circle with a fixed icon (Landmark, Droplets, TrendingUp, Rocket). The section wrapper uses `p-10` padding and an ambient blur decoration. The result is visually heavy and slow to scan — the user cannot quickly read the causal path from headline to market impact.

## Goal

Replace the large-circle design with a compact vertical step ladder so the user can scan the full causal path at a glance. The chain should feel like a lean structural annotation, not a hero element.

## Scope

Two files only. No backend changes. No new components.

- `frontend/src/components/ui/transmission-chain.tsx` — redesign `TransmissionChain`
- `frontend/src/components/pages/analysis-view.tsx` — strip the heavy section wrapper

`TransmissionChainCompact` (used in market mover cards) is **not modified**.

## Component Design — `TransmissionChain`

### Visual structure

Vertical list. Each step has:
- **Left column** (16px wide): small dot (7–8px) + vertical connector line below (omitted on last step)
- **Right column**: semantic label (9px uppercase teal/muted) + step text (12px)

### Dot colors
- First step and last step: teal accent (`bg-primary/20 border-primary/60`)
- All middle steps: muted (`bg-surface-container border-outline-variant/50`)

### Semantic labels (positional, index-based)

| Index | Label |
|-------|-------|
| 0 (always) | Trigger |
| 1 | Channel |
| 2 | Mechanism |
| 3 | Market |
| last (always) | Impact |

For a 3-step chain: Trigger → Channel → Impact  
For a 4-step chain: Trigger → Channel → Mechanism → Impact  
For a 5-step chain: Trigger → Channel → Mechanism → Market → Impact

The first-step rule (Trigger) takes priority over the last-step rule (Impact) when `steps.length === 1`. In practice the backend enforces ≥2 steps, so this is an unreachable edge case.

### Props

```typescript
export function TransmissionChain({ steps }: { steps: string[] }) {
  // returns null if steps is empty
}
```

No prop changes — same interface as before.

## Section Wrapper — `analysis-view.tsx`

### Before

```tsx
<section className={cn(SECTION_CARD, "p-10 relative overflow-hidden")}>
  <div className="absolute top-0 right-0 w-64 h-64 bg-primary/4 blur-[100px] -mr-32 -mt-32" />
  <h3 className="text-[10px] font-bold uppercase tracking-[0.3em] text-on-surface-variant mb-10 text-center relative z-10">
    Event Transmission Architecture
  </h3>
  <div className="relative z-10">
    <TransmissionChain steps={result.analysis.transmission_chain} />
  </div>
</section>
```

### After

```tsx
<section className={cn(SECTION_CARD, "px-5 py-4")}>
  <p className="section-kicker mb-4">Transmission Path</p>
  <TransmissionChain steps={result.analysis.transmission_chain} />
</section>
```

The conditional gate (`transmission_chain && transmission_chain.length > 0`) is unchanged.

## Testing

`frontend/src/components/ui/__tests__/transmission-chain.test.ts` — pure unit tests for the redesigned component:
- 3-step chain renders "Trigger", "Channel", "Impact" labels
- 4-step chain renders "Trigger", "Channel", "Mechanism", "Impact"
- 5-step chain renders all five positional labels
- Empty array returns null
- First and last steps get accent dot class; middle steps get muted dot class

TypeScript check (`npx tsc --noEmit`) must be clean after changes.
