/**
 * Q3 — honest track-record framing.
 *
 * The strip must LEAD with avg support ratio (the continuous evidence-strength
 * metric) and label the binary OR-rule count as "Any-supporting" — never as a
 * "Validated" / "Hit rate" verdict, because one supporting ticker can outweigh
 * several contradicting ones.  Contradicting + unresolved cases stay visible.
 *
 * Tests the pure computeTrackRecordDisplay() helper plus a render smoke of the
 * TrackRecordStrip (renderToStaticMarkup, the project's no-jsdom pattern).
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { computeTrackRecordDisplay, TrackRecordStrip } from "../market-overview";
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

describe("computeTrackRecordDisplay — honest framing", () => {
  it("leads with avg support ratio as an integer percentage", () => {
    expect(computeTrackRecordDisplay(makeData({ avg_support_ratio: 0.463 })).avgSupport).toBe(46);
  });
  it("returns null avg support when the ratio is null", () => {
    expect(computeTrackRecordDisplay(makeData({ avg_support_ratio: null })).avgSupport).toBeNull();
  });
  it("exposes the OR-rule count as 'anySupporting', not a validation verdict", () => {
    expect(computeTrackRecordDisplay(makeData({ validated: 48 })).anySupporting).toBe(48);
  });
  it("computes resolved = any-supporting + contradicted", () => {
    expect(computeTrackRecordDisplay(makeData({ validated: 48, contradicted: 12 })).resolved).toBe(60);
  });
  it("keeps the OR-rule rate available but secondary (anySupportingRate)", () => {
    expect(computeTrackRecordDisplay(makeData({ validated: 48, contradicted: 12 })).anySupportingRate).toBe(80);
  });
  it("returns null OR-rule rate when nothing resolved", () => {
    expect(computeTrackRecordDisplay(makeData({ validated: 0, contradicted: 0 })).anySupportingRate).toBeNull();
  });
  it("no longer exposes a 'hitRate' / 'hitTone' field (validation framing removed)", () => {
    const d = computeTrackRecordDisplay(makeData()) as Record<string, unknown>;
    expect("hitRate" in d).toBe(false);
    expect("hitTone" in d).toBe(false);
  });
});

describe("TrackRecordStrip — honest labels", () => {
  // 1 supporting + 4 contradicting must NOT read as fully "validated".
  const html = renderToStaticMarkup(
    <TrackRecordStrip
      data={makeData({ validated: 1, contradicted: 4, unresolved: 0, avg_support_ratio: 0.2 })}
      isLoading={false}
    />,
  );
  it("leads with avg support and labels the binary count 'Any-supporting'", () => {
    expect(html).toContain("Avg support");
    expect(html).toContain("Any-supporting");
  });
  it("removes 'Validated' / 'Hit rate' verdict framing", () => {
    expect(html).not.toContain("Validated");
    expect(html).not.toContain("Hit rate");
  });
  it("keeps contradicting and unresolved cases visible", () => {
    expect(html).toContain("Contradicted");
    expect(html).toContain("Unresolved");
  });
  it("carries a descriptive-evidence caveat and no banned overclaim words", () => {
    expect(html.toLowerCase()).toContain("descriptive evidence, not a verdict");
    for (const w of ["proves", "alpha", "signal", "buy", "sell", "prediction"]) {
      expect(html.toLowerCase()).not.toContain(w);
    }
  });
});
