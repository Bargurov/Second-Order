/**
 * Unit tests for the Position Simulator pure helpers.
 * No React mount needed — pure functions only.
 */
import { describe, it, expect } from "vitest";
import {
  groupPositionsByEvent,
  formatReturn,
} from "../portfolio-page";
import type { SimulatePosition } from "@/lib/api";

function makePos(overrides: Partial<SimulatePosition>): SimulatePosition {
  return {
    event_id: 1,
    event_headline: "Test event",
    event_date: "2024-01-01",
    event_confidence: "high",
    symbol: "XOM",
    role: "equity",
    direction_tag: "supports",
    weight: 0.5,
    gross_return: null,
    portfolio_return: null,
    return_source: "missing",
    short: false,
    ...overrides,
  };
}

describe("groupPositionsByEvent", () => {
  it("returns an empty map for empty input", () => {
    expect(groupPositionsByEvent([])).toEqual(new Map());
  });

  it("groups single position into its event bucket", () => {
    const pos = makePos({ event_id: 1, symbol: "XOM" });
    const result = groupPositionsByEvent([pos]);
    expect(result.size).toBe(1);
    expect(result.get(1)).toEqual([pos]);
  });

  it("groups multiple positions under the same event_id", () => {
    const a = makePos({ event_id: 1, symbol: "XOM" });
    const b = makePos({ event_id: 1, symbol: "CVX" });
    const result = groupPositionsByEvent([a, b]);
    expect(result.size).toBe(1);
    expect(result.get(1)).toEqual([a, b]);
  });

  it("separates positions across different event_ids", () => {
    const a = makePos({ event_id: 1, symbol: "XOM" });
    const b = makePos({ event_id: 2, symbol: "FCX" });
    const c = makePos({ event_id: 1, symbol: "CVX" });
    const result = groupPositionsByEvent([a, b, c]);
    expect(result.size).toBe(2);
    expect(result.get(1)).toEqual([a, c]);
    expect(result.get(2)).toEqual([b]);
  });

  it("preserves insertion order", () => {
    const positions = [
      makePos({ event_id: 3, symbol: "A" }),
      makePos({ event_id: 1, symbol: "B" }),
      makePos({ event_id: 2, symbol: "C" }),
    ];
    const keys = [...groupPositionsByEvent(positions).keys()];
    expect(keys).toEqual([3, 1, 2]);
  });
});

describe("formatReturn", () => {
  it("returns em-dash for null", () => {
    expect(formatReturn(null)).toBe("—");
  });

  it("formats positive return with leading +", () => {
    expect(formatReturn(4.2)).toBe("+4.2%");
  });

  it("formats negative return with minus sign", () => {
    expect(formatReturn(-2.1)).toBe("-2.1%");
  });

  it("formats zero with leading +", () => {
    expect(formatReturn(0)).toBe("+0.0%");
  });

  it("rounds to one decimal place", () => {
    expect(formatReturn(1.234)).toBe("+1.2%");
    expect(formatReturn(-3.789)).toBe("-3.8%");
  });
});
