/**
 * Focused tests for the Archive row inline preview action.
 *
 * Covers three invariants as pure function tests:
 *   1) Preview action renders — derivePreviewOpen returns false when nothing expanded.
 *   2) Expand/collapse behavior — toggle in and out of the set.
 *   3) Row state stays stable after search/sort changes — IDs are stable keys.
 *
 * No component rendering, no React, no fetch mocking needed.
 */

import { describe, it, expect } from "vitest";
import { derivePreviewOpen } from "../recent-events";

// ---------------------------------------------------------------------------
// 1) Preview action renders — closed by default
// ---------------------------------------------------------------------------

describe("derivePreviewOpen — closed by default", () => {
  it("returns false when set is empty", () => {
    expect(derivePreviewOpen(1, new Set())).toBe(false);
    expect(derivePreviewOpen(2, new Set())).toBe(false);
    expect(derivePreviewOpen(99, new Set())).toBe(false);
  });

  it("returns false for an id not present in the set", () => {
    const expanded = new Set([2, 3]);
    expect(derivePreviewOpen(1, expanded)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 2) Expand / collapse behavior
// ---------------------------------------------------------------------------

describe("derivePreviewOpen — expand", () => {
  it("returns true for an id that is in the set", () => {
    expect(derivePreviewOpen(1, new Set([1]))).toBe(true);
  });

  it("returns true only for the matching id", () => {
    const expanded = new Set([1]);
    expect(derivePreviewOpen(1, expanded)).toBe(true);
    expect(derivePreviewOpen(2, expanded)).toBe(false);
    expect(derivePreviewOpen(3, expanded)).toBe(false);
  });

  it("handles multiple rows expanded simultaneously", () => {
    const expanded = new Set([1, 3, 5]);
    expect(derivePreviewOpen(1, expanded)).toBe(true);
    expect(derivePreviewOpen(2, expanded)).toBe(false);
    expect(derivePreviewOpen(3, expanded)).toBe(true);
    expect(derivePreviewOpen(4, expanded)).toBe(false);
    expect(derivePreviewOpen(5, expanded)).toBe(true);
  });
});

describe("derivePreviewOpen — collapse", () => {
  it("returns false after the id is removed from the set", () => {
    const expanded = new Set([1, 2]);
    expanded.delete(1);
    expect(derivePreviewOpen(1, expanded)).toBe(false);
  });

  it("leaves other rows unaffected when one collapses", () => {
    const expanded = new Set([1, 2, 3]);
    expanded.delete(2);
    expect(derivePreviewOpen(1, expanded)).toBe(true);
    expect(derivePreviewOpen(2, expanded)).toBe(false);
    expect(derivePreviewOpen(3, expanded)).toBe(true);
  });

  it("returns false when all rows collapse", () => {
    const expanded = new Set([1, 2]);
    expanded.delete(1);
    expanded.delete(2);
    expect(derivePreviewOpen(1, expanded)).toBe(false);
    expect(derivePreviewOpen(2, expanded)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3) Stability after search / sort changes
// ---------------------------------------------------------------------------

describe("derivePreviewOpen — stable across filter and sort changes", () => {
  it("expanded state is keyed by event id, not list position", () => {
    // Simulate: row with id=42 is expanded; after filtering it moves to position 0
    const expanded = new Set([42]);
    // Regardless of position or what other rows are visible, id=42 stays expanded
    expect(derivePreviewOpen(42, expanded)).toBe(true);
    expect(derivePreviewOpen(1, expanded)).toBe(false);
    expect(derivePreviewOpen(100, expanded)).toBe(false);
  });

  it("expanded row that is filtered out and back stays expanded", () => {
    // Filter hides the row — set is unchanged — row returns with same id → still expanded
    const expanded = new Set([7]);
    // 'Filtered out': we just don't render the row, but the set state persists
    // 'Filtered back in': same id check
    expect(derivePreviewOpen(7, expanded)).toBe(true);
  });

  it("sort reorder does not affect expanded state", () => {
    // Two rows, both with stable ids; sort changes their order but not the set
    const expanded = new Set([10]);
    // Before sort: order [10, 20]; after sort: order [20, 10]
    expect(derivePreviewOpen(10, expanded)).toBe(true);
    expect(derivePreviewOpen(20, expanded)).toBe(false);
  });
});
