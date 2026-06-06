/**
 * Pins the P8D Section-1 restructure: a compact Regime band above a
 * full-width Uncertainty & Funding module whose four zones lay out in a
 * responsive grid, with zero-visual `data-term` hooks so term-level
 * explanations can be wired cleanly later (no popovers, no card expansion,
 * no "How to read this" accordion in this slice).
 *
 *  - UncertaintyCard: four labelled zones (State / Drivers / Horizon /
 *    Interpretation) in a responsive 2-col grid that stacks on mobile.
 *  - data-term hooks present on the enumerated terms (funding modes, funding
 *    severity, stress flags, HY−IG, horizon rows).
 *  - RegimeVectorCard: compact band preserves headline / confidence / chips /
 *    rationale; no banned overclaim words.
 */

import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { UncertaintyCard, RegimeVectorCard } from "../market-overview";
import type { FundingStressMode, StressRegime } from "@/lib/api";

function funding(over: Partial<FundingStressMode> = {}): FundingStressMode {
  return {
    available: true,
    primary_mode: "dollar_shortage",
    composite_severity: "elevated",
    active_modes: ["dollar_shortage"],
    rationale: "r",
    modes: {
      duration_shock: { fired: false, severity: "none", drivers: [], rationale: "" },
      dollar_shortage: { fired: true, severity: "elevated", drivers: ["DXY +1.17%/5d"], rationale: "" },
    },
    ...over,
  } as FundingStressMode;
}
function stress(over: Partial<StressRegime> = {}): StressRegime & { available?: boolean } {
  return {
    regime: "Calm",
    signals: {
      vix_elevated: true,
      term_inversion: false,
      credit_widening: false,
      safe_haven_bid: false,
      breadth_deterioration: false,
    },
    raw: {},
    summary: "calm tape",
    available: true,
    ...over,
  } as StressRegime & { available?: boolean };
}

const uncProps = {
  stress: stress(),
  funding: funding(),
  creditRegime: { available: true, regime_label: "Rates-driven bond weakness", hy_ig_differential_5d: 0.12 },
  explanation: {
    meaning: "Composite cross-asset stress regime across volatility, credit, and breadth.",
    what_changes_it: "VIX falling back below its 20d average.",
  },
};

describe("UncertaintyCard — P8D full-width module structure", () => {
  it("lays the four zones out in a responsive grid that stacks on mobile", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...uncProps} />);
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("sm:grid-cols-2");
  });

  it("labels all four zones", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...uncProps} />);
    for (const zone of ["State", "Drivers", "Horizon", "Interpretation"]) {
      expect(html).toContain(`>${zone}<`);
    }
  });

  it("exposes data-term hooks on the enumerated terms for later explanations", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...uncProps} />);
    for (const hook of [
      'data-term="dollar_shortage"',
      'data-term="funding_severity"',
      'data-term="vix_elevated"',
      'data-term="hy_ig"',
      'data-term="horizon_secular"',
    ]) {
      expect(html).toContain(hook);
    }
  });

  it("still renders the P8B content (driver-first, horizon copy) unweakened", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...uncProps} />);
    expect(html).toContain("DXY +1.17%/5d");
    expect(html).toContain("first repricing");
  });
});

describe("RegimeVectorCard — P8D compact band", () => {
  const regimeVec = {
    available: true,
    inflation: "hot",
    policy_stance: "hawkish",
    fx: "neutral",
    growth_stress: "neutral",
    credit: "neutral",
    curve_shape: "neutral",
    inflation_path: "neutral",
    compound: { label: "inflation_shock", confidence: 0.72, rationale: "Hot inflation with a hawkish Fed." },
  };

  it("preserves headline, confidence, and rationale in the band", () => {
    const html = renderToStaticMarkup(
      <RegimeVectorCard regimeVec={regimeVec as never} explanation={{ meaning: "m" }} />,
    );
    expect(html).toContain("Regime read");
    expect(html).toContain("Inflation shock");
    expect(html).toContain("Confidence");
    expect(html).toContain("72%");
    expect(html).toContain("Hot inflation with a hawkish Fed.");
  });

  it("renders off-neutral axis chips", () => {
    const text = renderToStaticMarkup(
      <RegimeVectorCard regimeVec={regimeVec as never} explanation={null} />,
    )
      .replace(/<[^>]*>/g, " ")
      .toLowerCase();
    expect(text).toContain("hawkish");
  });

  it("carries no banned overclaim / trading words", () => {
    const text = renderToStaticMarkup(
      <RegimeVectorCard regimeVec={regimeVec as never} explanation={{ meaning: "m", what_changes_it: "w" }} />,
    )
      .replace(/<[^>]*>/g, " ")
      .toLowerCase();
    for (const w of ["buy", "sell", "alpha", "signal", "proof", "proves"]) {
      expect(text).not.toContain(w);
    }
  });
});
