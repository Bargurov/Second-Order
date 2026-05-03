/**
 * Unit tests for TrackRecordStrip render/state logic.
 *
 * Tests the pure computeTrackRecordDisplay() function — no React rendering.
 */

import { describe, it, expect } from "vitest";
import { computeTrackRecordDisplay } from "../market-overview";
import type { TrackRecord } from "@/lib/api";

function makeData(overrides: Partial<TrackRecord> = {}): TrackRecord {
  return {
    total: 84,
    validated: 48,
    contradicted: 13,
    unresolved: 23,
    avg_support_ratio: 0.46,
    revisit_scored: 5,
    rated_good: 0,
    rated_mixed: 0,
    rated_poor: 0,
    ...overrides,
  };
}

describe("computeTrackRecordDisplay", () => {
  it("computes hit rate from validated / resolved", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 48, contradicted: 12 }));
    // 48 / 60 = 80%
    expect(d.hitRate).toBe(80);
    expect(d.resolved).toBe(60);
  });

  it("returns null hit rate when nothing resolved", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 0, contradicted: 0 }));
    expect(d.hitRate).toBeNull();
    expect(d.resolved).toBe(0);
    expect(d.hitTone).toBe("neutral");
  });

  it("returns positive tone for hit rate >= 60%", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 60, contradicted: 40 }));
    expect(d.hitRate).toBe(60);
    expect(d.hitTone).toBe("positive");
  });

  it("returns neutral tone for hit rate 40-59%", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 50, contradicted: 50 }));
    expect(d.hitRate).toBe(50);
    expect(d.hitTone).toBe("neutral");
  });

  it("returns warn tone for hit rate < 40%", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 10, contradicted: 90 }));
    expect(d.hitRate).toBe(10);
    expect(d.hitTone).toBe("warn");
  });

  it("rounds hit rate to nearest integer", () => {
    // 2 / 3 = 66.67% → 67
    const d = computeTrackRecordDisplay(makeData({ validated: 2, contradicted: 1 }));
    expect(d.hitRate).toBe(67);
  });

  it("computes avg support as integer percentage", () => {
    const d = computeTrackRecordDisplay(makeData({ avg_support_ratio: 0.463 }));
    expect(d.avgSupport).toBe(46);
  });

  it("returns null avg support when ratio is null", () => {
    const d = computeTrackRecordDisplay(makeData({ avg_support_ratio: null }));
    expect(d.avgSupport).toBeNull();
  });

  it("handles 100% hit rate", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 50, contradicted: 0 }));
    expect(d.hitRate).toBe(100);
    expect(d.hitTone).toBe("positive");
  });

  it("handles 0% hit rate", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 0, contradicted: 10 }));
    expect(d.hitRate).toBe(0);
    expect(d.hitTone).toBe("warn");
  });

  it("boundary: exactly 40% is neutral not warn", () => {
    const d = computeTrackRecordDisplay(makeData({ validated: 40, contradicted: 60 }));
    expect(d.hitRate).toBe(40);
    expect(d.hitTone).toBe("neutral");
  });
});
