import { describe, expect, it } from "vitest";
import { buildUncertaintyConcentrationView } from "../market-overview";
import type { NewsUncertaintyConcentration } from "@/lib/api";

function uc(overrides: Partial<NewsUncertaintyConcentration>): NewsUncertaintyConcentration {
  return {
    available: true,
    uncertainty_scope: "sector",
    sector_uncertainty: [],
    lead_sector: null,
    ...overrides,
  };
}

describe("buildUncertaintyConcentrationView", () => {
  it("shows normalized percentages for sector-led real data", () => {
    const view = buildUncertaintyConcentrationView(uc({
      uncertainty_scope: "sector",
      lead_sector: "energy",
      sector_uncertainty: [
        { sector: "energy", score: 6, cluster_count: 3, high_fraction: 0.67 },
        { sector: "defense", score: 3, cluster_count: 2, high_fraction: 0.5 },
      ],
    }));

    expect(view.entries.map((entry) => entry.value)).toEqual(["67%", "33%"]);
    expect(view.valueLabel).toBe("weighted score share");
    expect(view.footer).toContain("energy leads");
    expect(view.footer).not.toMatch(/unavailable|below the concentration threshold/i);
  });

  it("keeps mixed real data visible without unavailable or diffuse copy", () => {
    const view = buildUncertaintyConcentrationView(uc({
      uncertainty_scope: "mixed",
      sector_uncertainty: [
        { sector: "energy", score: 4, cluster_count: 2, high_fraction: 0.5 },
        { sector: "industrials", score: 4, cluster_count: 2, high_fraction: 0.5 },
      ],
    }));

    expect(view.entries).toHaveLength(2);
    expect(view.footer).toContain("Real sector-level signal is present");
    expect(`${view.emptyCopy} ${view.footer}`).not.toMatch(/unavailable|diffuse/i);
  });

  it("does not render bars when rows exist below the concentration threshold", () => {
    const view = buildUncertaintyConcentrationView(uc({
      uncertainty_scope: "global",
      sector_uncertainty: [
        { sector: "energy", score: 2, cluster_count: 1, high_fraction: 0 },
      ],
    }));

    expect(view.entries).toEqual([]);
    expect(view.emptyCopy).toContain("Sector scores exist");
    expect(view.emptyCopy).not.toContain("unavailable");
    expect(view.footer).toContain("below the concentration threshold");
  });

  it("keeps unavailable state separate from real sector rows", () => {
    const view = buildUncertaintyConcentrationView(uc({
      available: false,
      uncertainty_scope: "sector",
      lead_sector: "energy",
      sector_uncertainty: [
        { sector: "energy", score: 8, cluster_count: 4, high_fraction: 1 },
      ],
    }));

    expect(view.entries).toEqual([]);
    expect(view.emptyCopy).toContain("unavailable");
    expect(view.footer).toContain("did not return a usable block");
  });
});
