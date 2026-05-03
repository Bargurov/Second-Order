/**
 * Focused tests for the Archive page client-side sort logic.
 *
 * Tests the pure sortEvents function — no React rendering needed.
 */

import { describe, it, expect } from "vitest";
import { sortEvents, type SortKey } from "../recent-events";
import type { SavedEvent, Ticker } from "@/lib/api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function ticker(return_5d: number | null): Ticker {
  return {
    symbol: "XOM",
    role: "beneficiary",
    label: "in motion",
    direction_tag: "supports thesis",
    return_1d: null,
    return_5d,
    return_20d: null,
    volume_ratio: null,
    vs_xle_5d: null,
    spark: [],
  } as Ticker;
}

function ev(overrides: Partial<SavedEvent> & { id: number }): SavedEvent {
  return {
    timestamp: "2026-04-13T10:00:00",
    headline: "Test",
    stage: "realized",
    persistence: "medium",
    what_changed: "",
    mechanism_summary: "",
    beneficiaries: [],
    losers: [],
    assets_to_watch: [],
    confidence: "medium",
    market_note: "",
    market_tickers: [],
    event_date: "2026-04-13",
    notes: "",
    rating: null,
    ...overrides,
  };
}

const EVENTS: SavedEvent[] = [
  ev({ id: 1, timestamp: "2026-04-10T08:00:00", confidence: "low",
       market_tickers: [ticker(1.5)] }),
  ev({ id: 2, timestamp: "2026-04-12T14:00:00", confidence: "high",
       market_tickers: [ticker(5.0), ticker(-3.0)] }),
  ev({ id: 3, timestamp: "2026-04-11T10:00:00", confidence: "medium",
       market_tickers: [ticker(null)] }),
  ev({ id: 4, timestamp: "2026-04-13T09:00:00", confidence: "high",
       market_tickers: [ticker(0.5), ticker(-8.0)] }),
  ev({ id: 5, timestamp: "2026-04-09T16:00:00", confidence: "medium",
       market_tickers: [] }),
];

// ---------------------------------------------------------------------------
// Newest sort — must match server-side ORDER BY id DESC so pagination is
// consistent between the two sides.
// ---------------------------------------------------------------------------

describe("sort by newest", () => {
  it("orders by id descending (matches server ORDER BY id DESC)", () => {
    const result = sortEvents(EVENTS, "newest");
    expect(result.map((e) => e.id)).toEqual([5, 4, 3, 2, 1]);
  });

  it("does not mutate input", () => {
    const before = EVENTS.map((e) => e.id);
    sortEvents(EVENTS, "newest");
    expect(EVENTS.map((e) => e.id)).toEqual(before);
  });

  it("agrees with server paginator even when timestamps contradict id order", () => {
    // id order and timestamp order diverge (legacy timestamp skew, manual
    // resave, daylight savings).  The client must still match the server.
    const rows = [
      ev({ id: 10, timestamp: "2026-04-01T00:00:00" }),  // lowest ts
      ev({ id: 11, timestamp: "2026-04-03T00:00:00" }),  // highest ts
      ev({ id: 12, timestamp: "2026-04-02T00:00:00" }),  // middle ts
    ];
    // Server would return id DESC: [12, 11, 10].
    expect(sortEvents(rows, "newest").map((e) => e.id)).toEqual([12, 11, 10]);
  });
});

// ---------------------------------------------------------------------------
// Oldest sort — id ASC, mirror of the newest contract.
// ---------------------------------------------------------------------------

describe("sort by oldest", () => {
  it("orders by id ascending (mirrors server newest order)", () => {
    const result = sortEvents(EVENTS, "oldest");
    expect(result.map((e) => e.id)).toEqual([1, 2, 3, 4, 5]);
  });
});

// ---------------------------------------------------------------------------
// Impact sort
// ---------------------------------------------------------------------------

describe("sort by impact", () => {
  it("orders by max abs(return_5d) descending", () => {
    const result = sortEvents(EVENTS, "impact");
    // id4: max(0.5, 8.0)=8.0, id2: max(5.0, 3.0)=5.0, id1: 1.5, id3: 0 (null), id5: 0 (empty)
    expect(result.map((e) => e.id)).toEqual([4, 2, 1, 3, 5]);
  });

  it("null return_5d treated as zero impact", () => {
    const result = sortEvents(EVENTS, "impact");
    // id3 (null ticker) and id5 (no tickers) both have 0 impact → after real movers
    const nullIds = result.slice(-2).map((e) => e.id);
    expect(nullIds).toContain(3);
    expect(nullIds).toContain(5);
  });

  it("negative returns use absolute value", () => {
    const events = [
      ev({ id: 10, market_tickers: [ticker(-7.0)] }),
      ev({ id: 11, market_tickers: [ticker(3.0)] }),
    ];
    const result = sortEvents(events, "impact");
    expect(result[0]!.id).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// Confidence sort
// ---------------------------------------------------------------------------

describe("sort by confidence", () => {
  it("orders high → medium → low", () => {
    const result = sortEvents(EVENTS, "confidence");
    const confs = result.map((e) => e.confidence);
    // All high first, then medium, then low
    expect(confs).toEqual(["high", "high", "medium", "medium", "low"]);
  });

  it("preserves relative order within same confidence", () => {
    const result = sortEvents(EVENTS, "confidence");
    const highIds = result.filter((e) => e.confidence === "high").map((e) => e.id);
    // id2 and id4 are both high; original order preserved (stable sort)
    expect(highIds).toEqual([2, 4]);
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("edge cases", () => {
  it("empty array returns empty", () => {
    expect(sortEvents([], "newest")).toEqual([]);
  });

  it("single element returns same", () => {
    const single = [ev({ id: 99 })];
    expect(sortEvents(single, "impact")).toHaveLength(1);
    expect(sortEvents(single, "impact")[0]!.id).toBe(99);
  });

  it("all sort keys produce same length", () => {
    const keys: SortKey[] = ["newest", "oldest", "impact", "confidence"];
    for (const k of keys) {
      expect(sortEvents(EVENTS, k)).toHaveLength(EVENTS.length);
    }
  });
});
