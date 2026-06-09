/**
 * Unit tests for the Portfolio row's compact engine-phase helpers.
 * Pure-function tests — no React mount needed.
 */
import { describe, it, expect } from "vitest";
import {
  compactWarnings,
  formatQualityTier,
  formatSubtype,
  isLowInfoRow,
  tradableFlag,
} from "../portfolio-page";

describe("formatQualityTier", () => {
  it("maps known tiers to short labels", () => {
    expect(formatQualityTier("actionable")).toBe("high-quality");
    expect(formatQualityTier("watch_only")).toBe("watch");
    expect(formatQualityTier("low_information")).toBe("low info");
  });

  it("returns null for missing/unknown tiers", () => {
    expect(formatQualityTier(undefined)).toBeNull();
    expect(formatQualityTier(null)).toBeNull();
  });
});

describe("formatSubtype", () => {
  it("returns null for empty / null-like inputs", () => {
    expect(formatSubtype(null, "policy")).toBeNull();
    expect(formatSubtype(undefined, "policy")).toBeNull();
    expect(formatSubtype("", "policy")).toBeNull();
    expect(formatSubtype("none", "policy")).toBeNull();
    expect(formatSubtype("   ", "policy")).toBeNull();
  });

  it("drops a redundant family-equal subtype", () => {
    expect(formatSubtype("policy", "policy")).toBeNull();
    expect(formatSubtype("Policy", "policy")).toBeNull();
  });

  it("normalises underscores into spaces for display", () => {
    expect(formatSubtype("supply_shock", "energy")).toBe("supply shock");
  });

  it("preserves a distinct subtype unchanged otherwise", () => {
    expect(formatSubtype("tariff", "policy")).toBe("tariff");
  });
});

describe("tradableFlag", () => {
  it("returns null for missing / non-dict input", () => {
    expect(tradableFlag(undefined)).toBeNull();
    expect(tradableFlag(null)).toBeNull();
    expect(tradableFlag({})).toBeNull();
  });

  it("returns true / false when tradable is a boolean", () => {
    expect(tradableFlag({ tradable: true })).toBe(true);
    expect(tradableFlag({ tradable: false })).toBe(false);
  });

  it("returns null for a non-boolean tradable field", () => {
    expect(tradableFlag({ tradable: null })).toBeNull();
    expect(
      tradableFlag({ tradable: "yes" as unknown as boolean }),
    ).toBeNull();
  });
});

describe("isLowInfoRow", () => {
  it("is true only for the low_information tier", () => {
    expect(isLowInfoRow("low_information")).toBe(true);
  });

  it("is false for actionable / watch_only / unknown", () => {
    expect(isLowInfoRow("actionable")).toBe(false);
    expect(isLowInfoRow("watch_only")).toBe(false);
    expect(isLowInfoRow(undefined)).toBe(false);
    expect(isLowInfoRow(null as never)).toBe(false);
  });
});

describe("compactWarnings", () => {
  it("returns an empty array for non-list input", () => {
    expect(compactWarnings(null)).toEqual([]);
    expect(compactWarnings(undefined)).toEqual([]);
  });

  it("filters non-strings and trims empties", () => {
    expect(
      compactWarnings([
        "weak_mechanism",
        "",
        "   ",
        null as unknown as string,
        42 as unknown as string,
      ]),
    ).toEqual(["weak_mechanism"]);
  });

  it("dedupes while preserving order", () => {
    expect(
      compactWarnings([
        "weak_mechanism",
        "missing_asset_rationale",
        "weak_mechanism",
      ]),
    ).toEqual(["weak_mechanism", "missing_asset_rationale"]);
  });

  it("caps at the requested length (default 3)", () => {
    expect(
      compactWarnings([
        "weak_mechanism",
        "missing_asset_rationale",
        "invalid_chain",
        "no_observable_condition",
        "inconsistent_proof",
      ]),
    ).toEqual([
      "weak_mechanism",
      "missing_asset_rationale",
      "invalid_chain",
    ]);
  });

  it("respects a custom cap", () => {
    expect(
      compactWarnings(["a", "b", "c"], 2),
    ).toEqual(["a", "b"]);
  });
});
