/**
 * Unit tests for the Headlines Policy Tracker pure helpers.
 *
 * The component renders an active-first list with overflow tucked behind
 * an expand toggle.  These tests cover the contract of the two pure
 * helpers that drive that ordering:
 *
 *   - ``_sortPolicyItems`` strips ``status === "past"`` and orders the
 *     rest revisit_due → active → pre_effective → announced, ties
 *     broken by proximity (days_until / days_until_revisit ascending).
 *   - ``_splitPolicyVisibility`` returns the top-N visible items + the
 *     remainder hidden.  When ``expanded`` is true everything is
 *     visible and the hidden bucket is empty.
 *
 * Both helpers are pure — no React mount needed.
 */

import { describe, it, expect } from "vitest";
import { _sortPolicyItems, _splitPolicyVisibility } from "../headlines-page";
import type { PolicyItem, PolicyStatus, PolicyType } from "@/lib/api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeItem(overrides: Partial<PolicyItem> = {}): PolicyItem {
  return {
    name: "Item",
    policy_type: "tariff",
    jurisdiction: "US",
    effective_date: "2026-05-01",
    announcement_date: "2026-04-01",
    revisit_date: "2026-06-01",
    description: "",
    status: "active",
    days_until: 0,
    days_until_revisit: 0,
    ...overrides,
  };
}

const TYPE_VARIANTS: PolicyType[] = [
  "tariff",
  "sanction",
  "regulation",
  "executive_order",
  "rate_decision",
];

// ---------------------------------------------------------------------------
// _sortPolicyItems — filter past, status-first sort, proximity tie-break
// ---------------------------------------------------------------------------

describe("_sortPolicyItems", () => {
  it("returns [] for an empty input", () => {
    expect(_sortPolicyItems([])).toEqual([]);
  });

  it("strips items with status 'past'", () => {
    const items = [
      makeItem({ name: "live",   status: "active" }),
      makeItem({ name: "stale",  status: "past" }),
      makeItem({ name: "due",    status: "revisit_due" }),
    ];
    const out = _sortPolicyItems(items);
    expect(out.map((i) => i.name)).not.toContain("stale");
    expect(out).toHaveLength(2);
  });

  it("orders revisit_due first, then active, pre_effective, announced", () => {
    const items = [
      makeItem({ name: "ann", status: "announced" }),
      makeItem({ name: "act", status: "active" }),
      makeItem({ name: "pre", status: "pre_effective" }),
      makeItem({ name: "due", status: "revisit_due" }),
    ];
    expect(_sortPolicyItems(items).map((i) => i.name)).toEqual([
      "due",
      "act",
      "pre",
      "ann",
    ]);
  });

  it("breaks ties within revisit_due by days_until_revisit ascending", () => {
    const items = [
      makeItem({ name: "due-5", status: "revisit_due", days_until_revisit: 5 }),
      makeItem({ name: "due-1", status: "revisit_due", days_until_revisit: 1 }),
      makeItem({ name: "due-3", status: "revisit_due", days_until_revisit: 3 }),
    ];
    expect(_sortPolicyItems(items).map((i) => i.name)).toEqual([
      "due-1",
      "due-3",
      "due-5",
    ]);
  });

  it("breaks ties within pre_effective by days_until ascending", () => {
    const items = [
      makeItem({ name: "in-7", status: "pre_effective", days_until: 7 }),
      makeItem({ name: "in-2", status: "pre_effective", days_until: 2 }),
      makeItem({ name: "in-0", status: "pre_effective", days_until: 0 }),
    ];
    expect(_sortPolicyItems(items).map((i) => i.name)).toEqual([
      "in-0",
      "in-2",
      "in-7",
    ]);
  });

  it("does not mutate the input array", () => {
    const items = [
      makeItem({ name: "ann", status: "announced" }),
      makeItem({ name: "due", status: "revisit_due" }),
    ];
    const snapshot = items.slice();
    _sortPolicyItems(items);
    expect(items).toEqual(snapshot);
  });

  it("preserves every supported policy_type during sort (no type-based filtering)", () => {
    const items: PolicyItem[] = TYPE_VARIANTS.map((t, i) =>
      makeItem({ name: t, policy_type: t, status: "active", days_until: i }),
    );
    const out = _sortPolicyItems(items);
    expect(out.map((i) => i.policy_type).sort()).toEqual([...TYPE_VARIANTS].sort());
  });

  it("places revisit_due ahead of active even when active is closer in time", () => {
    const items = [
      makeItem({ name: "act-now", status: "active",      days_until: 0 }),
      makeItem({ name: "due-far", status: "revisit_due", days_until_revisit: 30 }),
    ];
    expect(_sortPolicyItems(items).map((i) => i.name)).toEqual([
      "due-far",
      "act-now",
    ]);
  });

  it("handles the all-past edge case by returning []", () => {
    const items: PolicyItem[] = (["past", "past"] as PolicyStatus[]).map((s, i) =>
      makeItem({ name: `p${i}`, status: s }),
    );
    expect(_sortPolicyItems(items)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// _splitPolicyVisibility — top-N visible, rest hidden behind expand
// ---------------------------------------------------------------------------

describe("_splitPolicyVisibility", () => {
  function lst(n: number): PolicyItem[] {
    return Array.from({ length: n }, (_, i) => makeItem({ name: `i${i}` }));
  }

  it("shows everything when items <= visibleCount", () => {
    const items = lst(3);
    const split = _splitPolicyVisibility(items, false, 4);
    expect(split.visible).toHaveLength(3);
    expect(split.hidden).toHaveLength(0);
  });

  it("collapses overflow to the hidden bucket when items > visibleCount", () => {
    const items = lst(7);
    const split = _splitPolicyVisibility(items, false, 4);
    expect(split.visible).toHaveLength(4);
    expect(split.hidden).toHaveLength(3);
    expect(split.visible.map((i) => i.name)).toEqual(["i0", "i1", "i2", "i3"]);
    expect(split.hidden.map((i) => i.name)).toEqual(["i4", "i5", "i6"]);
  });

  it("expands to show every item when expanded=true", () => {
    const items = lst(7);
    const split = _splitPolicyVisibility(items, true, 4);
    expect(split.visible).toHaveLength(7);
    expect(split.hidden).toHaveLength(0);
  });

  it("respects the default visible count of 4 when not overridden", () => {
    const items = lst(10);
    const split = _splitPolicyVisibility(items, false);
    expect(split.visible).toHaveLength(4);
    expect(split.hidden).toHaveLength(6);
  });

  it("returns empty buckets for an empty input regardless of expansion", () => {
    expect(_splitPolicyVisibility([], false, 4)).toEqual({ visible: [], hidden: [] });
    expect(_splitPolicyVisibility([], true,  4)).toEqual({ visible: [], hidden: [] });
  });

  it("supports a 3-item top-N (brief allows 3-5 visible)", () => {
    const items = lst(8);
    const split = _splitPolicyVisibility(items, false, 3);
    expect(split.visible).toHaveLength(3);
    expect(split.hidden).toHaveLength(5);
  });

  it("supports a 5-item top-N (brief allows 3-5 visible)", () => {
    const items = lst(8);
    const split = _splitPolicyVisibility(items, false, 5);
    expect(split.visible).toHaveLength(5);
    expect(split.hidden).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// Combined contract — the helpers chain into the rendered view
// ---------------------------------------------------------------------------

describe("sort + split pipeline", () => {
  it("the most-urgent revisit_due item lands in the visible bucket first", () => {
    const items = [
      makeItem({ name: "ann",  status: "announced",     days_until: 1 }),
      makeItem({ name: "act",  status: "active" }),
      makeItem({ name: "due1", status: "revisit_due",   days_until_revisit: 1 }),
      makeItem({ name: "due2", status: "revisit_due",   days_until_revisit: 0 }),
      makeItem({ name: "pre",  status: "pre_effective", days_until: 5 }),
    ];
    const sorted = _sortPolicyItems(items);
    const { visible } = _splitPolicyVisibility(sorted, false, 3);
    expect(visible.map((i) => i.name)).toEqual(["due2", "due1", "act"]);
  });

  it("past items never appear, even when collapsed view would otherwise pick them up", () => {
    const items = [
      makeItem({ name: "p", status: "past" }),
      makeItem({ name: "a", status: "active" }),
    ];
    const sorted = _sortPolicyItems(items);
    const { visible, hidden } = _splitPolicyVisibility(sorted, false, 4);
    expect([...visible, ...hidden].map((i) => i.name)).toEqual(["a"]);
  });
});
