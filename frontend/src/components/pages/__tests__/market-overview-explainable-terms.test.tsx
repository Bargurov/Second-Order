/**
 * Pins the P8E explainable-term pattern on the Uncertainty & Funding module:
 * specific jargon terms render as subtle buttons (not whole-card expansion,
 * no accordion), and selecting one shows a stable in-card research-note panel.
 *
 *  - getTermExplanation: pure lookup → the plain-language read shown in the
 *    panel when a term is selected (null → the default prompt).
 *  - ExplanationPanel: renders the default prompt when nothing is selected,
 *    and the term's note (Plain meaning / Why it matters / What would change /
 *    Horizon caveat) when one is.
 *  - The terms render as <button data-term=...> inside the card; the card root
 *    itself is never a button (no whole-card expansion).
 *  - No banned overclaim / trading words in any explanation copy.
 */

import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import {
  UncertaintyCard,
  ExplanationPanel,
  getTermExplanation,
  EXPLANATION_DEFAULT,
} from "../market-overview";
import type { FundingStressMode, StressRegime } from "@/lib/api";

const TERM_KEYS = [
  "funding_severity",
  "dollar_shortage",
  "credit_widening",
  "liquidity_squeeze",
  "duration_shock",
  "vix_elevated",
  "hy_ig",
  "horizon_1d",
  "horizon_5d",
  "horizon_20d",
  "horizon_secular",
];

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
  explanation: { meaning: "m", what_changes_it: "w" },
};

describe("getTermExplanation", () => {
  it("returns the funding-severity read", () => {
    const e = getTermExplanation("funding_severity");
    expect(e).not.toBeNull();
    expect(e!.plainMeaning.length).toBeGreaterThan(0);
    expect(e!.whyItMatters.length).toBeGreaterThan(0);
  });

  it("returns the dollar-shortage read", () => {
    const e = getTermExplanation("dollar_shortage");
    expect(e!.title.toLowerCase()).toContain("dollar shortage");
    expect(e!.plainMeaning.toLowerCase()).toContain("dollar demand");
  });

  it("returns the HY−IG read", () => {
    const e = getTermExplanation("hy_ig");
    expect(e!.plainMeaning.toLowerCase()).toContain("high-yield");
    expect(e!.plainMeaning.toLowerCase()).toContain("investment-grade");
  });

  it("explains the secular baseline as outside the event claim", () => {
    const e = getTermExplanation("horizon_secular");
    const blob = `${e!.plainMeaning} ${e!.whyItMatters} ${e!.horizonCaveat ?? ""}`.toLowerCase();
    expect(blob).toContain("long-run");
    expect(blob).toContain("outside this event claim");
  });

  it("returns null for no / unknown term", () => {
    expect(getTermExplanation(null)).toBeNull();
    expect(getTermExplanation("not_a_term")).toBeNull();
  });
});

describe("ExplanationPanel", () => {
  it("shows the default prompt when nothing is selected", () => {
    const html = renderToStaticMarkup(<ExplanationPanel explanation={null} />);
    expect(html).toContain(EXPLANATION_DEFAULT);
  });

  it("shows the selected term's note when a term is selected", () => {
    const html = renderToStaticMarkup(
      <ExplanationPanel explanation={getTermExplanation("funding_severity")} />,
    );
    expect(html).not.toContain(EXPLANATION_DEFAULT);
    expect(html).toContain("Plain meaning");
    expect(html).toContain("Why it matters");
  });

  it("renders the dollar-shortage note content", () => {
    const html = renderToStaticMarkup(
      <ExplanationPanel explanation={getTermExplanation("dollar_shortage")} />,
    ).toLowerCase();
    expect(html).toContain("dollar demand");
  });
});

describe("UncertaintyCard — explainable terms are buttons, not card expansion", () => {
  const html = renderToStaticMarkup(<UncertaintyCard {...uncProps} />);

  it("renders the listed terms as buttons carrying their data-term", () => {
    for (const t of ["dollar_shortage", "funding_severity", "vix_elevated", "hy_ig", "horizon_secular"]) {
      expect(html).toMatch(new RegExp(`<button[^>]*data-term="${t}"`));
    }
  });

  it("never makes the whole card a button", () => {
    expect(html.trimStart().startsWith("<div")).toBe(true);
    expect(html.trimStart().startsWith("<button")).toBe(false);
  });

  it("shows the stable default panel before any term is selected", () => {
    expect(html).toContain(EXPLANATION_DEFAULT);
  });
});

describe("explanation copy honesty", () => {
  it("carries no banned overclaim / trading words across every term", () => {
    const blob = TERM_KEYS.map((k) => {
      const e = getTermExplanation(k)!;
      return `${e.title} ${e.plainMeaning} ${e.whyItMatters} ${e.whatWouldChange ?? ""} ${e.horizonCaveat ?? ""}`;
    })
      .join(" ")
      .toLowerCase();
    for (const w of ["buy", "sell", "alpha", "signal", "proof", "proves", "proven", "prediction", "predicted"]) {
      expect(blob).not.toContain(w);
    }
  });
});
