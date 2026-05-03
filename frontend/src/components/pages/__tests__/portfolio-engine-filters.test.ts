/**
 * Unit tests for the Portfolio engine-field filter helpers.
 * Pure-function tests — no React mount needed.
 */
import { describe, it, expect } from "vitest";
import {
  ENGINE_FILTERS_DEFAULT,
  applyEngineFilters,
  collectSubtypes,
  isEngineFilterActive,
  type EngineFilters,
} from "../portfolio-page";
import type { PortfolioEntry } from "@/lib/api";

function makeEntry(overrides: Partial<PortfolioEntry> = {}): PortfolioEntry {
  return {
    id: 1,
    headline: "Test event",
    event_date: "2026-04-01",
    timestamp: "2026-04-01T00:00:00",
    stage: null,
    persistence: null,
    mechanism_summary: "",
    beneficiaries: [],
    losers: [],
    market_tickers: [],
    confidence: null,
    rating: null,
    revisit_snapshots: [],
    validation_outcome: "no_data",
    support_ratio: null,
    quality_tier: null,
    quality_warnings: [],
    actionability_check: null,
    mechanism_subtype: null,
    thesis_state_reason: null,
    ...overrides,
  };
}

describe("isEngineFilterActive", () => {
  it("returns false for the default state", () => {
    expect(isEngineFilterActive(ENGINE_FILTERS_DEFAULT)).toBe(false);
  });

  it("returns true when any axis is non-default", () => {
    expect(
      isEngineFilterActive({
        ...ENGINE_FILTERS_DEFAULT,
        qualityTier: "actionable",
      }),
    ).toBe(true);
    expect(
      isEngineFilterActive({
        ...ENGINE_FILTERS_DEFAULT,
        tradable: "tradable",
      }),
    ).toBe(true);
    expect(
      isEngineFilterActive({
        ...ENGINE_FILTERS_DEFAULT,
        subtype: "supply shock",
      }),
    ).toBe(true);
  });
});

describe("applyEngineFilters", () => {
  const entries: PortfolioEntry[] = [
    makeEntry({
      id: 1,
      quality_tier: "actionable",
      actionability_check: { tradable: true },
      mechanism_subtype: "supply_shock",
      mechanism_family: "energy",
    } as Partial<PortfolioEntry>),
    makeEntry({
      id: 2,
      quality_tier: "watch_only",
      actionability_check: { tradable: false },
      mechanism_subtype: "tariff",
      mechanism_family: "policy",
    } as Partial<PortfolioEntry>),
    makeEntry({
      id: 3,
      quality_tier: "low_information",
      actionability_check: null,
      mechanism_subtype: null,
    }),
    makeEntry({
      id: 4,
      quality_tier: "actionable",
      actionability_check: { tradable: true },
      mechanism_subtype: "supply_shock",
      mechanism_family: "energy",
    } as Partial<PortfolioEntry>),
  ];

  it("returns a clean array for null input", () => {
    expect(applyEngineFilters(null, ENGINE_FILTERS_DEFAULT)).toEqual([]);
    expect(applyEngineFilters(undefined, ENGINE_FILTERS_DEFAULT)).toEqual([]);
  });

  it("returns a copy of all entries with no filters active", () => {
    const out = applyEngineFilters(entries, ENGINE_FILTERS_DEFAULT);
    expect(out).toHaveLength(entries.length);
    expect(out).not.toBe(entries);
  });

  it("filters by quality_tier", () => {
    const out = applyEngineFilters(entries, {
      ...ENGINE_FILTERS_DEFAULT,
      qualityTier: "actionable",
    });
    expect(out.map((e) => e.id)).toEqual([1, 4]);
  });

  it("filters by tradable=true", () => {
    const out = applyEngineFilters(entries, {
      ...ENGINE_FILTERS_DEFAULT,
      tradable: "tradable",
    });
    expect(out.map((e) => e.id)).toEqual([1, 4]);
  });

  it("filters by tradable=false", () => {
    const out = applyEngineFilters(entries, {
      ...ENGINE_FILTERS_DEFAULT,
      tradable: "not_tradable",
    });
    expect(out.map((e) => e.id)).toEqual([2]);
  });

  it("filters by tradable=unknown when actionability is missing", () => {
    const out = applyEngineFilters(entries, {
      ...ENGINE_FILTERS_DEFAULT,
      tradable: "unknown",
    });
    expect(out.map((e) => e.id)).toEqual([3]);
  });

  it("filters by mechanism subtype using the display label", () => {
    const out = applyEngineFilters(entries, {
      ...ENGINE_FILTERS_DEFAULT,
      subtype: "supply shock",
    });
    expect(out.map((e) => e.id)).toEqual([1, 4]);
  });

  it("composes multiple filters with AND semantics", () => {
    const out = applyEngineFilters(entries, {
      qualityTier: "actionable",
      tradable: "tradable",
      subtype: "supply shock",
    });
    expect(out.map((e) => e.id)).toEqual([1, 4]);
  });

  it("returns empty when no entries match the filter", () => {
    const out = applyEngineFilters(entries, {
      ...ENGINE_FILTERS_DEFAULT,
      qualityTier: "watch_only",
      tradable: "tradable",
    });
    expect(out).toEqual([]);
  });

  it("does not crash on entries with unknown / missing fields", () => {
    const oddEntries: PortfolioEntry[] = [
      makeEntry({ id: 10, quality_tier: undefined }),
      makeEntry({
        id: 11,
        actionability_check: undefined as unknown as PortfolioEntry["actionability_check"],
      }),
    ];
    expect(() =>
      applyEngineFilters(oddEntries, {
        qualityTier: "actionable",
        tradable: "tradable",
        subtype: "anything",
      }),
    ).not.toThrow();
  });
});

describe("collectSubtypes", () => {
  it("returns an empty array for null / undefined input", () => {
    expect(collectSubtypes(null)).toEqual([]);
    expect(collectSubtypes(undefined)).toEqual([]);
  });

  it("dedupes display labels and sorts alphabetically", () => {
    const entries: PortfolioEntry[] = [
      makeEntry({
        id: 1,
        mechanism_subtype: "tariff",
        mechanism_family: "policy",
      } as Partial<PortfolioEntry>),
      makeEntry({
        id: 2,
        mechanism_subtype: "supply_shock",
        mechanism_family: "energy",
      } as Partial<PortfolioEntry>),
      makeEntry({
        id: 3,
        mechanism_subtype: "supply_shock",
        mechanism_family: "energy",
      } as Partial<PortfolioEntry>),
    ];
    expect(collectSubtypes(entries)).toEqual(["supply shock", "tariff"]);
  });

  it("drops nulls, blanks, none, and family-equal redundancies", () => {
    const entries: PortfolioEntry[] = [
      makeEntry({ id: 1, mechanism_subtype: null }),
      makeEntry({ id: 2, mechanism_subtype: "" }),
      makeEntry({ id: 3, mechanism_subtype: "none" }),
      makeEntry({
        id: 4,
        mechanism_subtype: "policy",
        mechanism_family: "policy",
      } as Partial<PortfolioEntry>),
      makeEntry({
        id: 5,
        mechanism_subtype: "tariff",
        mechanism_family: "policy",
      } as Partial<PortfolioEntry>),
    ];
    expect(collectSubtypes(entries)).toEqual(["tariff"]);
  });
});
