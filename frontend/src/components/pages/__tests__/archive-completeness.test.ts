/**
 * Focused tests for deriveCompleteness — the pure function behind
 * the completeness badges on Archive rows.
 */

import { describe, it, expect } from "vitest";
import { deriveCompleteness, type CompletenessSignals } from "../recent-events";
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

function ev(overrides?: Partial<SavedEvent>): SavedEvent {
  return {
    id: 1,
    timestamp: "2026-04-13T10:00:00",
    headline: "Test",
    stage: "realized",
    persistence: "medium",
    what_changed: "Something",
    mechanism_summary: "Mechanism text",
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

// ---------------------------------------------------------------------------
// hasMarketData / tickerCount
// ---------------------------------------------------------------------------

describe("market data signals", () => {
  it("no tickers → hasMarketData false, tickerCount 0", () => {
    const s = deriveCompleteness(ev({ market_tickers: [] }));
    expect(s.hasMarketData).toBe(false);
    expect(s.tickerCount).toBe(0);
  });

  it("tickers with null return_5d → hasMarketData false", () => {
    const s = deriveCompleteness(ev({ market_tickers: [ticker(null)] }));
    expect(s.hasMarketData).toBe(false);
    expect(s.tickerCount).toBe(0);
  });

  it("one ticker with return_5d → hasMarketData true, tickerCount 1", () => {
    const s = deriveCompleteness(ev({ market_tickers: [ticker(3.5)] }));
    expect(s.hasMarketData).toBe(true);
    expect(s.tickerCount).toBe(1);
  });

  it("mixed null and real → counts only real", () => {
    const s = deriveCompleteness(ev({
      market_tickers: [ticker(3.5), ticker(null), ticker(-1.0)],
    }));
    expect(s.hasMarketData).toBe(true);
    expect(s.tickerCount).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// hasRating
// ---------------------------------------------------------------------------

describe("rating signal", () => {
  it("null rating → false", () => {
    expect(deriveCompleteness(ev({ rating: null })).hasRating).toBe(false);
  });

  it("empty string rating → false", () => {
    expect(deriveCompleteness(ev({ rating: "" })).hasRating).toBe(false);
  });

  it("'good' rating → true", () => {
    expect(deriveCompleteness(ev({ rating: "good" })).hasRating).toBe(true);
  });

  it("'poor' rating → true", () => {
    expect(deriveCompleteness(ev({ rating: "poor" })).hasRating).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// hasNotes
// ---------------------------------------------------------------------------

describe("notes signal", () => {
  it("empty notes → false", () => {
    expect(deriveCompleteness(ev({ notes: "" })).hasNotes).toBe(false);
  });

  it("non-empty notes → true", () => {
    expect(deriveCompleteness(ev({ notes: "Follow up on Monday" })).hasNotes).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// hasMechanism
// ---------------------------------------------------------------------------

describe("mechanism signal", () => {
  it("real mechanism → true", () => {
    expect(deriveCompleteness(ev({ mechanism_summary: "Higher rates slow demand" })).hasMechanism).toBe(true);
  });

  it("empty mechanism → false", () => {
    expect(deriveCompleteness(ev({ mechanism_summary: "" })).hasMechanism).toBe(false);
  });

  it("mock mechanism → false", () => {
    expect(deriveCompleteness(ev({ mechanism_summary: "[mock: overloaded]" })).hasMechanism).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Full event vs minimal event
// ---------------------------------------------------------------------------

describe("full vs minimal", () => {
  it("fully populated event has all signals true", () => {
    const s = deriveCompleteness(ev({
      market_tickers: [ticker(3.5), ticker(-1.0)],
      rating: "good",
      notes: "Confirmed thesis",
      mechanism_summary: "Supply shock lifts energy",
    }));
    expect(s.hasMarketData).toBe(true);
    expect(s.tickerCount).toBe(2);
    expect(s.hasRating).toBe(true);
    expect(s.hasNotes).toBe(true);
    expect(s.hasMechanism).toBe(true);
  });

  it("bare minimum event has minimal signals", () => {
    const s = deriveCompleteness(ev({
      market_tickers: [],
      rating: null,
      notes: "",
      mechanism_summary: "",
    }));
    expect(s.hasMarketData).toBe(false);
    expect(s.tickerCount).toBe(0);
    expect(s.hasRating).toBe(false);
    expect(s.hasNotes).toBe(false);
    expect(s.hasMechanism).toBe(false);
  });
});
