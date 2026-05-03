/**
 * Unit tests for market-validation-status render/state logic.
 *
 * Tests the pure deriveValidationStatus() and formatAge() functions.
 */

import { describe, it, expect } from "vitest";
import {
  deriveValidationStatus,
  formatAge,
  type ValidationStatus,
} from "../market-validation-status";
import type { MarketResult, FreshnessBlock } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMarket(overrides: Partial<MarketResult> = {}): MarketResult {
  return {
    note: "",
    details: {},
    tickers: [],
    ...overrides,
  };
}

const NOW = new Date("2026-04-12T12:00:00Z").getTime();

function isoMinutesAgo(mins: number): string {
  return new Date(NOW - mins * 60_000).toISOString();
}

// ---------------------------------------------------------------------------
// formatAge
// ---------------------------------------------------------------------------

describe("formatAge", () => {
  it("returns 'just now' for 0-1 minutes", () => {
    expect(formatAge(0)).toBe("just now");
    expect(formatAge(1)).toBe("just now");
  });

  it("returns minutes for 2-59", () => {
    expect(formatAge(5)).toBe("5m ago");
    expect(formatAge(59)).toBe("59m ago");
  });

  it("returns hours for 60-1439", () => {
    expect(formatAge(60)).toBe("1h ago");
    expect(formatAge(150)).toBe("2h ago");
    expect(formatAge(1439)).toBe("23h ago");
  });

  it("returns days for 1440+", () => {
    expect(formatAge(1440)).toBe("1d ago");
    expect(formatAge(4320)).toBe("3d ago");
  });
});

// ---------------------------------------------------------------------------
// deriveValidationStatus
// ---------------------------------------------------------------------------

describe("deriveValidationStatus", () => {
  it("returns null when market is undefined", () => {
    expect(deriveValidationStatus(undefined)).toBeNull();
  });

  it("returns null when market is null", () => {
    expect(deriveValidationStatus(null)).toBeNull();
  });

  // Error state
  it("returns error tone for staleness=error", () => {
    const s = deriveValidationStatus(
      makeMarket({ market_check_staleness: "error" }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("error");
    expect(s.label).toBe("Data error");
  });

  it("includes data_quality_note in error detail", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "error",
        data_quality_note: "yfinance timeout",
      }),
      null,
      NOW,
    )!;
    expect(s.detail).toBe("yfinance timeout");
  });

  // Frozen
  it("returns frozen tone for staleness=frozen", () => {
    const s = deriveValidationStatus(
      makeMarket({ market_check_staleness: "frozen" }),
      { is_frozen: true, event_age_days: 45 },
      NOW,
    )!;
    expect(s.tone).toBe("frozen");
    expect(s.label).toBe("Archived");
    expect(s.age).toBe("45d old");
  });

  it("returns frozen when freshness.is_frozen even without staleness field", () => {
    const s = deriveValidationStatus(
      makeMarket({}),
      { is_frozen: true, event_age_days: 60 },
      NOW,
    )!;
    expect(s.tone).toBe("frozen");
  });

  // Refreshed variants
  it("returns refreshed tone for stale_refreshed", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "stale_refreshed",
        last_market_check_at: isoMinutesAgo(3),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("refreshed");
    expect(s.label).toBe("Refreshed");
    expect(s.age).toBe("3m ago");
  });

  it("returns refreshed tone for forced_refreshed with detail", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "forced_refreshed",
        last_market_check_at: isoMinutesAgo(1),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("refreshed");
    expect(s.detail).toBe("Force-refreshed past freeze window");
  });

  it("returns refreshed tone for legacy_refreshed", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "legacy_refreshed",
        last_market_check_at: isoMinutesAgo(10),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("refreshed");
    expect(s.age).toBe("10m ago");
  });

  // Fresh cache hit
  it("returns live tone when fresh and recent (<=30m)", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "fresh",
        last_market_check_at: isoMinutesAgo(5),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("live");
    expect(s.label).toBe("Live");
    expect(s.age).toBe("5m ago");
  });

  it("returns stale tone when fresh but old (>30m)", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "fresh",
        last_market_check_at: isoMinutesAgo(120),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("stale");
    expect(s.label).toBe("Cached");
    expect(s.age).toBe("2h ago");
  });

  // Degraded quality overlay
  it("includes degraded quality note on any non-error status", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "fresh",
        last_market_check_at: isoMinutesAgo(2),
        data_quality: "degraded",
        data_quality_note: "3 of 5 tickers missing prices",
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("live");
    expect(s.detail).toBe("3 of 5 tickers missing prices");
  });

  // Legacy path — no staleness field
  it("derives from timestamp alone when staleness is missing", () => {
    const s = deriveValidationStatus(
      makeMarket({
        last_market_check_at: isoMinutesAgo(10),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("live");
    expect(s.label).toBe("Live");
  });

  it("returns stale on legacy path when timestamp is old", () => {
    const s = deriveValidationStatus(
      makeMarket({
        last_market_check_at: isoMinutesAgo(180),
      }),
      null,
      NOW,
    )!;
    expect(s.tone).toBe("stale");
    expect(s.label).toBe("Stale");
    expect(s.age).toBe("3h ago");
  });

  // No timestamp at all
  it("returns null when no staleness and no timestamp", () => {
    const s = deriveValidationStatus(makeMarket({}), null, NOW);
    expect(s).toBeNull();
  });

  // Edge: frozen event_age_days from market field
  it("reads event_age_days from market when freshness lacks it", () => {
    const s = deriveValidationStatus(
      makeMarket({
        market_check_staleness: "frozen",
        event_age_days: 30,
      }),
      { is_frozen: true },
      NOW,
    )!;
    expect(s.age).toBe("30d old");
  });
});
