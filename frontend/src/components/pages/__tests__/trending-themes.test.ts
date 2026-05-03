import { describe, it, expect } from "vitest";
import { deriveThemes } from "../market-overview";
import type { NewsCluster, RegimeVector } from "@/lib/api";

function makeCluster(overrides: Partial<NewsCluster> & {
  action?: string;
  sector?: string;
}): NewsCluster {
  const { action, sector, ...rest } = overrides;
  return {
    headline: "Test headline",
    sources: [],
    source_count: 1,
    consensus: {
      ...(action !== undefined && { action }),
      ...(sector !== undefined && { sector }),
    },
    ...rest,
  };
}

function makeRegime(overrides: Partial<RegimeVector> = {}): RegimeVector {
  return {
    inflation: "neutral",
    policy_stance: "neutral",
    fx: "neutral",
    growth_stress: "neutral",
    available: true,
    ...overrides,
  };
}

describe("deriveThemes", () => {
  it("returns empty list for empty clusters", () => {
    expect(deriveThemes([], null)).toEqual([]);
  });

  it("filters out themes below threshold (clusterCount < 2 AND sourceWeight < 4)", () => {
    const clusters = [makeCluster({ action: "tariffs", source_count: 1 })];
    expect(deriveThemes(clusters, null)).toEqual([]);
  });

  it("includes theme when clusterCount >= 2", () => {
    const clusters = [
      makeCluster({ action: "tariffs", source_count: 1 }),
      makeCluster({ action: "tariffs", source_count: 1 }),
    ];
    const result = deriveThemes(clusters, null);
    expect(result).toHaveLength(1);
    expect(result[0].label).toBe("tariffs");
    expect(result[0].clusterCount).toBe(2);
  });

  it("includes theme when sourceWeight >= 4 even with clusterCount 1", () => {
    const clusters = [makeCluster({ action: "defense", source_count: 4 })];
    const result = deriveThemes(clusters, null);
    expect(result).toHaveLength(1);
    expect(result[0].label).toBe("defense");
    expect(result[0].sourceWeight).toBe(4);
  });

  it("excludes low_signal clusters from aggregation", () => {
    const clusters = [
      makeCluster({ action: "tariffs", source_count: 1, low_signal: true }),
      makeCluster({ action: "tariffs", source_count: 1, low_signal: true }),
    ];
    expect(deriveThemes(clusters, null)).toEqual([]);
  });

  it("normalises labels to lowercase and trims whitespace", () => {
    const clusters = [
      makeCluster({ action: "  Tariffs  ", source_count: 2 }),
      makeCluster({ action: "TARIFFS", source_count: 2 }),
    ];
    const result = deriveThemes(clusters, null);
    expect(result).toHaveLength(1);
    expect(result[0].label).toBe("tariffs");
  });

  it('skips consensus entries with "unknown", "none", "n/a"', () => {
    const clusters = [
      makeCluster({ action: "unknown", source_count: 3 }),
      makeCluster({ action: "unknown", source_count: 3 }),
      makeCluster({ action: "none", source_count: 3 }),
      makeCluster({ action: "none", source_count: 3 }),
    ];
    expect(deriveThemes(clusters, null)).toEqual([]);
  });

  it("handles clusters with no consensus field", () => {
    const clusters: NewsCluster[] = [
      { headline: "a", sources: [], source_count: 3, consensus: undefined },
      { headline: "b", sources: [], source_count: 3, consensus: undefined },
    ];
    expect(deriveThemes(clusters, null)).toEqual([]);
  });

  it("aggregates sourceWeight across clusters for same label", () => {
    const clusters = [
      makeCluster({ sector: "energy", source_count: 2 }),
      makeCluster({ sector: "energy", source_count: 3 }),
    ];
    const result = deriveThemes(clusters, null);
    expect(result[0].sourceWeight).toBe(5);
    expect(result[0].clusterCount).toBe(2);
  });

  it("marks regimeAligned when tariff matches fx stressed", () => {
    const clusters = [
      makeCluster({ action: "tariffs", source_count: 2 }),
      makeCluster({ action: "tariffs", source_count: 2 }),
    ];
    const regime = makeRegime({ fx: "dollar_strong" });
    const result = deriveThemes(clusters, regime);
    expect(result[0].regimeAligned).toBe(true);
  });

  it("marks regimeAligned when energy/oil matches inflation hot", () => {
    const clusters = [
      makeCluster({ sector: "energy", source_count: 2 }),
      makeCluster({ sector: "energy", source_count: 2 }),
    ];
    const regime = makeRegime({ inflation: "hot" });
    const result = deriveThemes(clusters, regime);
    expect(result[0].regimeAligned).toBe(true);
  });

  it("does not mark regimeAligned when energy but inflation neutral", () => {
    const clusters = [
      makeCluster({ sector: "energy", source_count: 2 }),
      makeCluster({ sector: "energy", source_count: 2 }),
    ];
    const regime = makeRegime({ inflation: "neutral" });
    const result = deriveThemes(clusters, regime);
    expect(result[0].regimeAligned).toBe(false);
  });

  it("does not mark regimeAligned when regimeVec is null", () => {
    const clusters = [
      makeCluster({ action: "tariffs", source_count: 3 }),
      makeCluster({ action: "tariffs", source_count: 3 }),
    ];
    const result = deriveThemes(clusters, null);
    expect(result[0].regimeAligned).toBe(false);
  });

  it("does not mark regimeAligned when regimeVec.available is false", () => {
    const clusters = [
      makeCluster({ action: "tariffs", source_count: 2 }),
      makeCluster({ action: "tariffs", source_count: 2 }),
    ];
    const regime = makeRegime({ fx: "dollar_strong", available: false });
    const result = deriveThemes(clusters, regime);
    expect(result[0].regimeAligned).toBe(false);
  });

  it("sorts regime-aligned themes first", () => {
    const clusters = [
      makeCluster({ action: "tariffs", source_count: 2 }),
      makeCluster({ action: "tariffs", source_count: 2 }),
      makeCluster({ sector: "technology", source_count: 5 }),
      makeCluster({ sector: "technology", source_count: 5 }),
    ];
    const regime = makeRegime({ fx: "dollar_weak" });
    const result = deriveThemes(clusters, regime);
    expect(result[0].label).toBe("tariffs");
    expect(result[0].regimeAligned).toBe(true);
    expect(result[1].label).toBe("technology");
    expect(result[1].regimeAligned).toBe(false);
  });

  it("sorts by combined score (clusterCount*2 + sourceWeight) within alignment group", () => {
    const clusters = [
      makeCluster({ sector: "financials", source_count: 1 }),
      makeCluster({ sector: "financials", source_count: 1 }),
      makeCluster({ sector: "technology", source_count: 3 }),
      makeCluster({ sector: "technology", source_count: 3 }),
    ];
    const result = deriveThemes(clusters, null);
    // technology: score = 2*2 + 6 = 10; financials: score = 2*2 + 2 = 6
    expect(result[0].label).toBe("technology");
    expect(result[1].label).toBe("financials");
  });

  it("caps output at 7 themes", () => {
    const labels = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"];
    const clusters: NewsCluster[] = labels.flatMap((action) => [
      makeCluster({ action, source_count: 2 }),
      makeCluster({ action, source_count: 2 }),
    ]);
    const result = deriveThemes(clusters, null);
    expect(result).toHaveLength(7);
  });

  it("treats action and sector as independent categories", () => {
    const clusters = [
      makeCluster({ action: "sanctions", sector: "energy", source_count: 2 }),
      makeCluster({ action: "sanctions", sector: "energy", source_count: 2 }),
    ];
    const result = deriveThemes(clusters, null);
    expect(result).toHaveLength(2);
    const categories = result.map((t) => t.category).sort();
    expect(categories).toEqual(["action", "sector"]);
  });
});
