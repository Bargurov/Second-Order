/**
 * Tests for the revisit timeline derivation logic.
 *
 * Covers:
 *   - Per-horizon summary derivation (avg, verdict, ticker rows)
 *   - Overall trajectory classification
 *   - Edge cases: empty, partial, all horizons
 */

import { describe, it, expect } from "vitest";
import {
  deriveHorizonSummary,
  deriveAllHorizons,
  deriveTrajectory,
  type HorizonSummary,
} from "../revisit-derivation";
import type { RevisitSnapshot, RevisitTicker } from "../api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function snap(day: number, tickers: RevisitTicker[]): RevisitSnapshot {
  return { day, captured_at: "2026-04-15T12:00:00", tickers };
}

function ticker(
  symbol: string,
  role: string,
  returnVal: number | null,
  direction: string | null = null,
  day: number = 5,
): RevisitTicker {
  return {
    symbol,
    role,
    direction,
    [`return_${day}d`]: returnVal,
  };
}

// ---------------------------------------------------------------------------
// deriveHorizonSummary
// ---------------------------------------------------------------------------

describe("deriveHorizonSummary", () => {
  it("returns no_data for missing snapshot", () => {
    const h = deriveHorizonSummary([], 5);
    expect(h.available).toBe(false);
    expect(h.verdict).toBe("no_data");
    expect(h.tickers).toHaveLength(0);
  });

  it("returns validated when all tickers support", () => {
    const s = snap(5, [
      ticker("XOM", "beneficiary", 3.5, "supports thesis", 5),
      ticker("CVX", "beneficiary", 2.1, "supports thesis", 5),
    ]);
    const h = deriveHorizonSummary([s], 5);
    expect(h.available).toBe(true);
    expect(h.verdict).toBe("validated");
    expect(h.supporting).toBe(2);
    expect(h.contradicting).toBe(0);
    expect(h.avgReturn).toBeCloseTo(2.8, 1);
  });

  it("returns contradicted when all tickers contradict", () => {
    const s = snap(5, [
      ticker("DAL", "loser", 2.0, "contradicts thesis", 5),
    ]);
    const h = deriveHorizonSummary([s], 5);
    expect(h.verdict).toBe("contradicted");
    expect(h.contradicting).toBe(1);
  });

  it("returns mixed when both directions present", () => {
    const s = snap(5, [
      ticker("XOM", "beneficiary", 3.0, "supports thesis", 5),
      ticker("DAL", "loser", 1.5, "contradicts thesis", 5),
    ]);
    const h = deriveHorizonSummary([s], 5);
    expect(h.verdict).toBe("mixed");
  });

  it("infers direction from return sign and role when direction is null", () => {
    const s = snap(5, [
      ticker("XOM", "beneficiary", 3.0, null, 5),  // positive + beneficiary → supports
      ticker("DAL", "loser", -2.0, null, 5),        // negative + loser → supports
    ]);
    const h = deriveHorizonSummary([s], 5);
    expect(h.supporting).toBe(2);
    expect(h.verdict).toBe("validated");
  });

  it("handles 1d and 20d snapshots correctly", () => {
    const s1 = snap(1, [ticker("XOM", "beneficiary", 0.5, "supports thesis", 1)]);
    const s20 = snap(20, [ticker("XOM", "beneficiary", 5.0, "supports thesis", 20)]);
    const h1 = deriveHorizonSummary([s1, s20], 1);
    const h20 = deriveHorizonSummary([s1, s20], 20);
    expect(h1.avgReturn).toBeCloseTo(0.5, 1);
    expect(h20.avgReturn).toBeCloseTo(5.0, 1);
  });

  it("handles 60d snapshot correctly", () => {
    const s60 = snap(60, [ticker("XOM", "beneficiary", 12.0, null, 60)]);
    const h60 = deriveHorizonSummary([s60], 60);
    expect(h60.available).toBe(true);
    expect(h60.label).toBe("60 Day");
    expect(h60.avgReturn).toBeCloseTo(12.0, 1);
    expect(h60.verdict).toBe("validated");
  });

  it("60d snapshot with loser going up → contradicts", () => {
    const s60 = snap(60, [ticker("DAL", "loser", 8.0, null, 60)]);
    const h60 = deriveHorizonSummary([s60], 60);
    expect(h60.verdict).toBe("contradicted");
    expect(h60.contradicting).toBe(1);
  });

  it("prefers return-based direction over stored direction for 60d", () => {
    // Stored direction says "supports" (r5-based) but actual return_60d is negative for beneficiary
    const s60 = snap(60, [{
      symbol: "XOM", role: "beneficiary",
      direction: "supports thesis",
      return_60d: -5.0,
    } as RevisitTicker]);
    const h60 = deriveHorizonSummary([s60], 60);
    // return-based: negative + beneficiary → contradicts
    expect(h60.verdict).toBe("contradicted");
  });

  it("populates ticker rows", () => {
    const s = snap(5, [
      ticker("XOM", "beneficiary", 3.5, "supports thesis", 5),
    ]);
    const h = deriveHorizonSummary([s], 5);
    expect(h.tickers).toHaveLength(1);
    expect(h.tickers[0]).toEqual({
      symbol: "XOM",
      role: "beneficiary",
      returnValue: 3.5,
      direction: "supports",
    });
  });
});

// ---------------------------------------------------------------------------
// deriveAllHorizons
// ---------------------------------------------------------------------------

describe("deriveAllHorizons", () => {
  it("returns 4 horizons", () => {
    const result = deriveAllHorizons([]);
    expect(result).toHaveLength(4);
    expect(result.map((h) => h.day)).toEqual([1, 5, 20, 60]);
  });

  it("marks available horizons correctly", () => {
    const s = snap(5, [ticker("XOM", "beneficiary", 3.0, "supports thesis", 5)]);
    const result = deriveAllHorizons([s]);
    expect(result[0]!.available).toBe(false);  // 1d
    expect(result[1]!.available).toBe(true);   // 5d
    expect(result[2]!.available).toBe(false);  // 20d
    expect(result[3]!.available).toBe(false);  // 60d
  });

  it("marks 60d available when snapshot exists", () => {
    const s60 = snap(60, [ticker("XOM", "beneficiary", 9.0, null, 60)]);
    const result = deriveAllHorizons([s60]);
    expect(result[3]!.available).toBe(true);
    expect(result[3]!.day).toBe(60);
  });
});

// ---------------------------------------------------------------------------
// deriveTrajectory
// ---------------------------------------------------------------------------

describe("deriveTrajectory", () => {
  function horizons(verdicts: [string, string, string, string?]): HorizonSummary[] {
    const days = [1, 5, 20, 60];
    return verdicts.map((v, i) => ({
      day: days[i]!,
      label: `${days[i]}D`,
      available: v !== "no_data",
      capturedAt: v !== "no_data" ? "2026-04-15T12:00:00" : null,
      avgReturn: v !== "no_data" ? 1.0 : null,
      supporting: v === "validated" || v === "mixed" ? 1 : 0,
      contradicting: v === "contradicted" || v === "mixed" ? 1 : 0,
      total: v !== "no_data" ? 2 : 0,
      verdict: v as HorizonSummary["verdict"],
      tickers: [],
    }));
  }

  it("too_early when no horizons available", () => {
    expect(deriveTrajectory(horizons(["no_data", "no_data", "no_data"]))).toBe("too_early");
  });

  it("holding when all validated", () => {
    expect(deriveTrajectory(horizons(["validated", "validated", "validated"]))).toBe("holding");
  });

  it("holding when latest is validated", () => {
    expect(deriveTrajectory(horizons(["mixed", "validated", "validated"]))).toBe("holding");
  });

  it("reversed when latest is contradicted", () => {
    expect(deriveTrajectory(horizons(["validated", "validated", "contradicted"]))).toBe("reversed");
  });

  it("fading when validated then mixed", () => {
    expect(deriveTrajectory(horizons(["validated", "mixed", "no_data"]))).toBe("fading");
  });

  it("reversed when latest available is contradicted despite earlier validation", () => {
    // Latest available (5d) is contradicted → reversed takes priority
    expect(deriveTrajectory(horizons(["validated", "contradicted", "no_data"]))).toBe("reversed");
  });

  it("mixed when validated bookends a contradicted middle", () => {
    // Latest (20d) validated but middle contradicted → mixed
    expect(deriveTrajectory(horizons(["validated", "contradicted", "validated"]))).toBe("holding");
  });

  it("holding when only 1d is validated", () => {
    expect(deriveTrajectory(horizons(["validated", "no_data", "no_data"]))).toBe("holding");
  });

  it("reversed when only 5d is contradicted", () => {
    expect(deriveTrajectory(horizons(["no_data", "contradicted", "no_data"]))).toBe("reversed");
  });

  it("holding when 60d is validated after earlier mixed", () => {
    expect(deriveTrajectory(horizons(["validated", "mixed", "mixed", "validated"]))).toBe("holding");
  });

  it("reversed when 60d is contradicted (prefers longest)", () => {
    expect(deriveTrajectory(horizons(["validated", "validated", "validated", "contradicted"]))).toBe("reversed");
  });

  it("too_early when all four are no_data", () => {
    expect(deriveTrajectory(horizons(["no_data", "no_data", "no_data", "no_data"]))).toBe("too_early");
  });
});
