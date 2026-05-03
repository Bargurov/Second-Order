/**
 * Focused tests for the Archive page client-side filter logic.
 *
 * Tests the pure filterEvents function — no React rendering needed.
 */

import { describe, it, expect } from "vitest";
import { filterEvents, type ArchiveFilters } from "../recent-events";
import type { SavedEvent } from "@/lib/api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function event(overrides: Partial<SavedEvent> & { headline: string }): SavedEvent {
  return {
    id: Math.random() * 10000 | 0,
    timestamp: "2026-04-13T10:00:00",
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
  event({ id: 1, headline: "Fed raises rates by 50bp", stage: "realized", confidence: "high", persistence: "high", rating: "good", timestamp: "2026-01-10T10:00:00", event_date: "2026-01-10" }),
  event({ id: 2, headline: "OPEC cuts output sharply", stage: "developing", confidence: "medium", persistence: "medium", rating: "mixed", timestamp: "2026-02-15T10:00:00", event_date: "2026-02-15" }),
  event({ id: 3, headline: "EU sanctions on Russia", stage: "anticipated", confidence: "low", persistence: "low", rating: null, timestamp: "2026-03-01T10:00:00", event_date: "2026-03-01" }),
  event({ id: 4, headline: "China stimulus package announced", stage: "realized", confidence: "high",
          mechanism_summary: "Fiscal boost to construction", persistence: "high", rating: "good", timestamp: "2026-03-20T10:00:00", event_date: "2026-03-20" }),
  event({ id: 5, headline: "UK inflation rises again", stage: "developing", confidence: "medium", persistence: "low", rating: "poor", timestamp: "2026-04-13T10:00:00", event_date: "2026-04-13" }),
];

const EMPTY: ArchiveFilters = { search: "", stage: null, confidence: null };

// ---------------------------------------------------------------------------
// Text search
// ---------------------------------------------------------------------------

describe("text search", () => {
  it("empty search returns all events", () => {
    expect(filterEvents(EVENTS, EMPTY)).toHaveLength(5);
  });

  it("headline match filters correctly", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, search: "fed" });
    expect(result).toHaveLength(1);
    expect(result[0]!.headline).toContain("Fed");
  });

  it("case-insensitive", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, search: "OPEC" });
    expect(result).toHaveLength(1);
  });

  it("partial match works", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, search: "sanction" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(3);
  });

  it("mechanism_summary also searched", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, search: "fiscal" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(4);
  });

  it("no match returns empty", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, search: "zzzznotfound" });
    expect(result).toHaveLength(0);
  });

  it("whitespace-only search returns all", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, search: "   " });
    expect(result).toHaveLength(5);
  });
});

// ---------------------------------------------------------------------------
// Stage filter
// ---------------------------------------------------------------------------

describe("stage filter", () => {
  it("null stage returns all", () => {
    expect(filterEvents(EVENTS, EMPTY)).toHaveLength(5);
  });

  it("realized filter", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, stage: "realized" });
    expect(result).toHaveLength(2);
    expect(result.every((e) => e.stage === "realized")).toBe(true);
  });

  it("developing filter", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, stage: "developing" });
    expect(result).toHaveLength(2);
  });

  it("anticipated filter", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, stage: "anticipated" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// Confidence filter
// ---------------------------------------------------------------------------

describe("confidence filter", () => {
  it("null confidence returns all", () => {
    expect(filterEvents(EVENTS, EMPTY)).toHaveLength(5);
  });

  it("high confidence", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, confidence: "high" });
    expect(result).toHaveLength(2);
    expect(result.every((e) => e.confidence === "high")).toBe(true);
  });

  it("low confidence", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, confidence: "low" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// Combined filters
// ---------------------------------------------------------------------------

describe("combined filters", () => {
  it("search + stage", () => {
    const result = filterEvents(EVENTS, {
      search: "inflation",
      stage: "developing",
      confidence: null,
    });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(5);
  });

  it("search + confidence", () => {
    const result = filterEvents(EVENTS, {
      search: "",
      stage: null,
      confidence: "high",
    });
    expect(result).toHaveLength(2);
  });

  it("stage + confidence", () => {
    const result = filterEvents(EVENTS, {
      search: "",
      stage: "realized",
      confidence: "high",
    });
    expect(result).toHaveLength(2);
  });

  it("all three narrow to one", () => {
    const result = filterEvents(EVENTS, {
      search: "stimulus",
      stage: "realized",
      confidence: "high",
    });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(4);
  });

  it("contradictory filters return empty", () => {
    const result = filterEvents(EVENTS, {
      search: "fed",
      stage: "anticipated",
      confidence: null,
    });
    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("edge cases", () => {
  it("empty events array", () => {
    expect(filterEvents([], EMPTY)).toHaveLength(0);
  });

  it("empty events with search", () => {
    expect(filterEvents([], { ...EMPTY, search: "test" })).toHaveLength(0);
  });

  it("order preserved", () => {
    const result = filterEvents(EVENTS, EMPTY);
    expect(result.map((e) => e.id)).toEqual([1, 2, 3, 4, 5]);
  });
});

// ---------------------------------------------------------------------------
// Persistence filter
// ---------------------------------------------------------------------------

describe("persistence filter", () => {
  it("null persistence returns all", () => {
    expect(filterEvents(EVENTS, { ...EMPTY, persistence: null })).toHaveLength(5);
  });

  it("undefined persistence returns all", () => {
    expect(filterEvents(EVENTS, EMPTY)).toHaveLength(5);
  });

  it("high persistence", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, persistence: "high" });
    expect(result).toHaveLength(2);
    expect(result.every((e) => e.persistence === "high")).toBe(true);
  });

  it("low persistence", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, persistence: "low" });
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.id)).toEqual([3, 5]);
  });

  it("medium persistence", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, persistence: "medium" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Rating filter
// ---------------------------------------------------------------------------

describe("rating filter", () => {
  it("null rating returns all", () => {
    expect(filterEvents(EVENTS, { ...EMPTY, rating: null })).toHaveLength(5);
  });

  it("undefined rating returns all", () => {
    expect(filterEvents(EVENTS, EMPTY)).toHaveLength(5);
  });

  it("good rating", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, rating: "good" });
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.id)).toEqual([1, 4]);
  });

  it("mixed rating", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, rating: "mixed" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(2);
  });

  it("poor rating", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, rating: "poor" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// Date range filter
// ---------------------------------------------------------------------------

describe("date range filter", () => {
  it("null dateFrom and dateTo returns all", () => {
    expect(filterEvents(EVENTS, { ...EMPTY, dateFrom: null, dateTo: null })).toHaveLength(5);
  });

  it("dateFrom filters events before date", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, dateFrom: "2026-03-01" });
    expect(result).toHaveLength(3);
    expect(result.map((e) => e.id)).toEqual([3, 4, 5]);
  });

  it("dateTo filters events after date", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, dateTo: "2026-02-15" });
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.id)).toEqual([1, 2]);
  });

  it("dateFrom + dateTo window", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, dateFrom: "2026-02-15", dateTo: "2026-03-20" });
    expect(result).toHaveLength(3);
    expect(result.map((e) => e.id)).toEqual([2, 3, 4]);
  });

  it("narrow window returns one", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, dateFrom: "2026-03-20", dateTo: "2026-03-20" });
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe(4);
  });

  it("window with no matches returns empty", () => {
    const result = filterEvents(EVENTS, { ...EMPTY, dateFrom: "2025-01-01", dateTo: "2025-12-31" });
    expect(result).toHaveLength(0);
  });
});
