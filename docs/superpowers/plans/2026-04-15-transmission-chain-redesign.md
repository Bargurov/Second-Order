# Transmission Chain Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current large-circle transmission chain with a compact vertical step ladder that shows the causal path from headline to market impact at a glance.

**Architecture:** Extract two pure helper functions (`getStepLabel`, `isAccentStep`) from the component logic, test them directly (no React mount needed), then rewrite `TransmissionChain` to use a vertical dot-and-line layout. Strip the heavy `p-10` section wrapper in `analysis-view.tsx` down to `px-5 py-4`.

**Tech Stack:** React, TypeScript, Tailwind CSS, vitest

---

## File Map

| File | Change |
|---|---|
| `frontend/src/components/ui/transmission-chain.tsx` | Replace `TransmissionChain` body; export two pure helpers; leave `TransmissionChainCompact` untouched |
| `frontend/src/components/ui/__tests__/transmission-chain.test.ts` | New — unit tests for `getStepLabel` and `isAccentStep` |
| `frontend/src/components/pages/analysis-view.tsx` | Strip the heavy section wrapper (lines 2182–2191) |

---

## Task 1: Write failing tests for the label helpers

**Files:**
- Create: `frontend/src/components/ui/__tests__/transmission-chain.test.ts`

- [ ] **Step 1: Create the test file**

```typescript
/**
 * Unit tests for TransmissionChain label and accent helpers.
 * Tests pure functions — no React mount needed.
 */
import { describe, it, expect } from "vitest";
import { getStepLabel, isAccentStep } from "../transmission-chain";

describe("getStepLabel", () => {
  it("always returns Trigger for index 0", () => {
    expect(getStepLabel(0, 3)).toBe("Trigger");
    expect(getStepLabel(0, 5)).toBe("Trigger");
  });

  it("always returns Impact for last index", () => {
    expect(getStepLabel(2, 3)).toBe("Impact");
    expect(getStepLabel(4, 5)).toBe("Impact");
  });

  it("3-step chain: Trigger, Channel, Impact", () => {
    expect(getStepLabel(0, 3)).toBe("Trigger");
    expect(getStepLabel(1, 3)).toBe("Channel");
    expect(getStepLabel(2, 3)).toBe("Impact");
  });

  it("4-step chain: Trigger, Channel, Mechanism, Impact", () => {
    expect(getStepLabel(0, 4)).toBe("Trigger");
    expect(getStepLabel(1, 4)).toBe("Channel");
    expect(getStepLabel(2, 4)).toBe("Mechanism");
    expect(getStepLabel(3, 4)).toBe("Impact");
  });

  it("5-step chain: Trigger, Channel, Mechanism, Market, Impact", () => {
    expect(getStepLabel(0, 5)).toBe("Trigger");
    expect(getStepLabel(1, 5)).toBe("Channel");
    expect(getStepLabel(2, 5)).toBe("Mechanism");
    expect(getStepLabel(3, 5)).toBe("Market");
    expect(getStepLabel(4, 5)).toBe("Impact");
  });

  it("falls back to Channel for unknown middle index", () => {
    // 7-step chain — index 4 and 5 are both middle, beyond the MIDDLE array
    expect(getStepLabel(4, 7)).toBe("Channel");
    expect(getStepLabel(5, 7)).toBe("Channel");
  });
});

describe("isAccentStep", () => {
  it("first step is always accent", () => {
    expect(isAccentStep(0, 3)).toBe(true);
    expect(isAccentStep(0, 5)).toBe(true);
  });

  it("last step is always accent", () => {
    expect(isAccentStep(2, 3)).toBe(true);
    expect(isAccentStep(4, 5)).toBe(true);
  });

  it("middle steps are not accent", () => {
    expect(isAccentStep(1, 3)).toBe(false);
    expect(isAccentStep(1, 5)).toBe(false);
    expect(isAccentStep(2, 5)).toBe(false);
    expect(isAccentStep(3, 5)).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests — confirm they fail**

```
cd frontend && npx vitest run src/components/ui/__tests__/transmission-chain.test.ts
```

Expected: `FAIL` — `getStepLabel` and `isAccentStep` are not exported yet.

---

## Task 2: Rewrite TransmissionChain

**Files:**
- Modify: `frontend/src/components/ui/transmission-chain.tsx` (full rewrite of the `TransmissionChain` function + new exports; `TransmissionChainCompact` untouched)

- [ ] **Step 1: Replace the file content**

Replace the entire file with:

```typescript
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

const MIDDLE_LABELS = ["Channel", "Mechanism", "Market"];

/** Returns the semantic label for a step at the given index in a chain of `total` steps. */
export function getStepLabel(index: number, total: number): string {
  if (index === 0) return "Trigger";
  if (index === total - 1) return "Impact";
  return MIDDLE_LABELS[index - 1] ?? "Channel";
}

/** Returns true if the step should use the accent (teal) dot color. */
export function isAccentStep(index: number, total: number): boolean {
  return index === 0 || index === total - 1;
}

// ---------------------------------------------------------------------------
// Full chain — vertical step ladder
// ---------------------------------------------------------------------------

export function TransmissionChain({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="flex flex-col">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const accent = isAccentStep(i, steps.length);
        const label = getStepLabel(i, steps.length);

        return (
          <div key={i} className="flex items-start gap-3">
            {/* Left column: dot + connector line */}
            <div className="flex flex-col items-center w-4 flex-shrink-0">
              <span
                className={cn(
                  "w-2 h-2 rounded-full border flex-shrink-0 mt-[3px]",
                  accent
                    ? "bg-primary/20 border-primary/60"
                    : "bg-surface-container border-outline-variant/50",
                )}
              />
              {!isLast && (
                <span className="w-px flex-1 min-h-[14px] bg-outline-variant/30 mt-1" />
              )}
            </div>
            {/* Right column: label + step text */}
            <div className={cn("pb-3", isLast && "pb-0")}>
              <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-primary/40 mb-0.5">
                {label}
              </p>
              <p className="text-[12px] text-on-surface leading-snug">{step}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact chain — horizontal for Market Mover cards (unchanged)
// ---------------------------------------------------------------------------

const COMPACT_LABELS = ["Event", "Channel", "Market", "Outcome"];

export function TransmissionChainCompact({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;
  const visible = steps.slice(0, 3);
  return (
    <div className="flex items-center gap-1 text-[10px] text-on-surface-variant overflow-hidden">
      {visible.map((step, i) => {
        const label = COMPACT_LABELS[i];
        const truncated = step.length > 60 ? step.slice(0, 57) + "..." : step;
        return (
          <span key={i} className="flex items-center gap-1 min-w-0">
            {i > 0 && <span className="text-outline-variant shrink-0">&rarr;</span>}
            <span className="truncate">
              {label && <span className="font-bold uppercase tracking-wide text-[9px] text-on-surface-variant/60">{label}: </span>}
              {truncated}
            </span>
          </span>
        );
      })}
    </div>
  );
}
```

Note: `STEP_LABELS` was `["Event", "Channel", "Market", "Outcome"]` — the compact component used this for its own labels. The rewrite keeps those labels in `COMPACT_LABELS` so `TransmissionChainCompact` is unaffected.

- [ ] **Step 2: Run tests — confirm they pass**

```
cd frontend && npx vitest run src/components/ui/__tests__/transmission-chain.test.ts
```

Expected: `PASS` — 13 tests (8 `getStepLabel` + 5 `isAccentStep`).

- [ ] **Step 3: Run full frontend test suite**

```
cd frontend && npx vitest run
```

Expected: all tests pass — no regressions.

- [ ] **Step 4: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: no output (clean).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/transmission-chain.tsx frontend/src/components/ui/__tests__/transmission-chain.test.ts
git commit -m "feat: redesign TransmissionChain as compact vertical step ladder"
```

---

## Task 3: Strip the heavy section wrapper in analysis-view.tsx

**Files:**
- Modify: `frontend/src/components/pages/analysis-view.tsx` (lines 2182–2191)

- [ ] **Step 1: Find and replace the section wrapper**

Locate this block (currently around line 2182):

```tsx
              {result.analysis.transmission_chain && result.analysis.transmission_chain.length > 0 && (
                <section className={cn(SECTION_CARD, "p-10 relative overflow-hidden")}>
                  <div className="absolute top-0 right-0 w-64 h-64 bg-primary/4 blur-[100px] -mr-32 -mt-32" />
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.3em] text-on-surface-variant mb-10 text-center relative z-10">
                    Event Transmission Architecture
                  </h3>
                  <div className="relative z-10">
                    <TransmissionChain steps={result.analysis.transmission_chain} />
                  </div>
                </section>
              )}
```

Replace with:

```tsx
              {result.analysis.transmission_chain && result.analysis.transmission_chain.length > 0 && (
                <section className={cn(SECTION_CARD, "px-5 py-4")}>
                  <p className="section-kicker mb-4">Transmission Path</p>
                  <TransmissionChain steps={result.analysis.transmission_chain} />
                </section>
              )}
```

- [ ] **Step 2: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 3: Run full frontend test suite**

```
cd frontend && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/pages/analysis-view.tsx
git commit -m "feat: strip heavy transmission chain section wrapper"
```

---

## Self-Review

**Spec coverage:**
- ✅ Step ladder layout (dot + connector line + label + text)
- ✅ Accent dots on first and last steps (`bg-primary/20 border-primary/60`)
- ✅ Muted dots on middle steps (`bg-surface-container border-outline-variant/50`)
- ✅ Semantic labels: Trigger / Channel / Mechanism / Market / Impact
- ✅ 3-step: Trigger, Channel, Impact
- ✅ 4-step: Trigger, Channel, Mechanism, Impact
- ✅ 5-step: Trigger, Channel, Mechanism, Market, Impact
- ✅ Empty array returns null
- ✅ `TransmissionChainCompact` unmodified
- ✅ Section wrapper: `px-5 py-4`, "Transmission Path" kicker, no blur
- ✅ Conditional gate unchanged
- ✅ TypeScript clean

**Placeholder scan:** None.

**Type consistency:** `getStepLabel(index: number, total: number): string` and `isAccentStep(index: number, total: number): boolean` used consistently in Task 2 component and Task 1 tests.
