/**
 * Focused tests for Archive row local pinning.
 *
 * Covers three invariants as pure function tests:
 *   1) Pin action renders — isPinned returns correct state from a Set.
 *   2) Pinned rows sort first — applyPinSort puts pins at top, preserving
 *      secondary order within each group.
 *   3) Pin state survives reload — loadPins / savePins round-trip via
 *      injectable storage (no DOM required).
 *
 * No component rendering, no React, no fetch mocking needed.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  isPinned,
  applyPinSort,
  loadPins,
  savePins,
  PINS_LS_KEY,
} from "../recent-events";
import type { SavedEvent } from "@/lib/api";

// ---------------------------------------------------------------------------
// Fake storage helper — mirrors the MinStorage interface used internally
// ---------------------------------------------------------------------------

function makeFakeStorage(): Pick<Storage, "getItem" | "setItem"> & { _store: Record<string, string> } {
  const _store: Record<string, string> = {};
  return {
    _store,
    getItem: (k: string) => _store[k] ?? null,
    setItem: (k: string, v: string) => { _store[k] = v; },
  };
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEvent(id: number, overrides: Partial<SavedEvent> = {}): SavedEvent {
  return {
    id,
    headline: `Event ${id}`,
    stage: "realized",
    persistence: "transitory",
    confidence: "medium",
    timestamp: `2026-04-13T10:0${id}:00`,
    event_date: "2026-04-13",
    what_changed: null,
    mechanism_summary: null,
    beneficiaries: [],
    losers: [],
    assets_to_watch: [],
    market_tickers: [],
    market_note: null,
    rating: null,
    notes: null,
    ...overrides,
  } as SavedEvent;
}

const E1 = makeEvent(1);
const E2 = makeEvent(2);
const E3 = makeEvent(3);
const E4 = makeEvent(4);

// ---------------------------------------------------------------------------
// 1) Pin action renders — isPinned
// ---------------------------------------------------------------------------

describe("isPinned — unpinned by default", () => {
  it("returns false when set is empty", () => {
    expect(isPinned(1, new Set())).toBe(false);
    expect(isPinned(99, new Set())).toBe(false);
  });

  it("returns false for id not in set", () => {
    expect(isPinned(1, new Set([2, 3]))).toBe(false);
  });
});

describe("isPinned — pinned state", () => {
  it("returns true for id in set", () => {
    expect(isPinned(1, new Set([1]))).toBe(true);
  });

  it("returns true only for matching id", () => {
    const pinned = new Set([2]);
    expect(isPinned(1, pinned)).toBe(false);
    expect(isPinned(2, pinned)).toBe(true);
    expect(isPinned(3, pinned)).toBe(false);
  });

  it("handles multiple pinned ids", () => {
    const pinned = new Set([1, 3]);
    expect(isPinned(1, pinned)).toBe(true);
    expect(isPinned(2, pinned)).toBe(false);
    expect(isPinned(3, pinned)).toBe(true);
  });

  it("returns false after id is removed from set", () => {
    const pinned = new Set([1, 2]);
    pinned.delete(1);
    expect(isPinned(1, pinned)).toBe(false);
    expect(isPinned(2, pinned)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 2) Pinned rows sort first — applyPinSort
// ---------------------------------------------------------------------------

describe("applyPinSort — no pins", () => {
  it("returns the list unchanged when nothing is pinned", () => {
    const list = [E1, E2, E3];
    expect(applyPinSort(list, new Set())).toEqual(list);
  });

  it("returns empty list unchanged", () => {
    expect(applyPinSort([], new Set([1]))).toEqual([]);
  });
});

describe("applyPinSort — single pin", () => {
  it("puts the pinned row first", () => {
    const result = applyPinSort([E1, E2, E3], new Set([2]));
    expect(result[0].id).toBe(2);
  });

  it("preserves relative order of non-pinned rows", () => {
    const result = applyPinSort([E1, E2, E3], new Set([2]));
    expect(result.map((e) => e.id)).toEqual([2, 1, 3]);
  });
});

describe("applyPinSort — multiple pins", () => {
  it("all pinned rows come before all unpinned rows", () => {
    const result = applyPinSort([E1, E2, E3, E4], new Set([2, 4]));
    const ids = result.map((e) => e.id);
    const pinGroup = ids.slice(0, 2).sort();
    const restGroup = ids.slice(2).sort();
    expect(pinGroup).toEqual([2, 4]);
    expect(restGroup).toEqual([1, 3]);
  });

  it("preserves source order within the pinned group", () => {
    const result = applyPinSort([E1, E2, E3, E4], new Set([2, 4]));
    expect(result[0].id).toBe(2);
    expect(result[1].id).toBe(4);
  });

  it("preserves source order within the unpinned group", () => {
    const result = applyPinSort([E1, E2, E3, E4], new Set([2, 4]));
    expect(result[2].id).toBe(1);
    expect(result[3].id).toBe(3);
  });
});

describe("applyPinSort — all rows pinned", () => {
  it("returns all rows in source order when all are pinned", () => {
    const result = applyPinSort([E1, E2, E3], new Set([1, 2, 3]));
    expect(result.map((e) => e.id)).toEqual([1, 2, 3]);
  });
});

describe("applyPinSort — pin not in current list", () => {
  it("ignores pinned ids that are not in the event list", () => {
    const result = applyPinSort([E1, E2, E3], new Set([99]));
    expect(result.map((e) => e.id)).toEqual([1, 2, 3]);
  });
});

// ---------------------------------------------------------------------------
// 3) Pin state survives reload — loadPins / savePins round-trip
// ---------------------------------------------------------------------------

describe("loadPins / savePins — round-trip via injectable storage", () => {
  let store: ReturnType<typeof makeFakeStorage>;

  beforeEach(() => {
    store = makeFakeStorage();
  });

  it("loadPins returns empty set when storage is empty", () => {
    expect(loadPins(store).size).toBe(0);
  });

  it("savePins then loadPins restores the same ids", () => {
    savePins(new Set([1, 5, 42]), store);
    const restored = loadPins(store);
    expect(restored.has(1)).toBe(true);
    expect(restored.has(5)).toBe(true);
    expect(restored.has(42)).toBe(true);
    expect(restored.size).toBe(3);
  });

  it("stores under the correct key", () => {
    savePins(new Set([7]), store);
    const raw = store.getItem(PINS_LS_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed).toContain(7);
  });

  it("overwriting with a smaller set removes old ids", () => {
    savePins(new Set([1, 2, 3]), store);
    savePins(new Set([2]), store);
    const restored = loadPins(store);
    expect(restored.has(1)).toBe(false);
    expect(restored.has(2)).toBe(true);
    expect(restored.has(3)).toBe(false);
  });

  it("savePins with empty set clears all pins", () => {
    savePins(new Set([1, 2]), store);
    savePins(new Set(), store);
    expect(loadPins(store).size).toBe(0);
  });

  it("returns empty set when storage is null", () => {
    expect(loadPins(null).size).toBe(0);
  });

  it("returns empty set when stored value is malformed JSON", () => {
    store.setItem(PINS_LS_KEY, "not-json{{");
    expect(loadPins(store).size).toBe(0);
  });

  it("returns empty set when stored value is not an array", () => {
    store.setItem(PINS_LS_KEY, JSON.stringify({ id: 1 }));
    expect(loadPins(store).size).toBe(0);
  });

  it("ignores non-integer entries in stored array", () => {
    store.setItem(PINS_LS_KEY, JSON.stringify([1, "abc", 2.5, null, 3]));
    const restored = loadPins(store);
    expect(restored.has(1)).toBe(true);
    expect(restored.has(3)).toBe(true);
    expect(restored.size).toBe(2);
  });

  it("savePins is a no-op when storage is null", () => {
    // Should not throw
    expect(() => savePins(new Set([1]), null)).not.toThrow();
  });
});
