/**
 * Pins the P8B "Uncertainty & Funding" deepening — funding/stress/credit
 * decomposition (driver-first), horizon discipline, and the interpretation
 * "what would change this read" line.
 *
 *  - selectFiringFundingModes: only fired modes, most-severe first, drivers
 *    carried verbatim, never invented; [] when unavailable / nothing fired.
 *  - selectFiringStressSignals: firing component flags only, canonical order.
 *  - selectCreditConfirmation: regime_label + hy_ig differential when available.
 *  - Horizon-discipline copy is exact; the secular baseline is explicitly
 *    outside the event claim.
 *  - The card renders drivers driver-first, the horizon block, and the
 *    what_changes_it line only when supplied — with none of the banned
 *    overclaim / trading words in its visible text.
 */

import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import {
  UncertaintyCard,
  selectFiringFundingModes,
  selectFiringStressSignals,
  selectCreditConfirmation,
  HORIZON_DISCIPLINE_NOTE,
  HORIZON_DISCIPLINE_PLAIN,
  HORIZON_ROWS,
  INTERPRETATION_WHAT_CHANGES_LABEL,
} from "../market-overview";
import type { FundingStressMode, StressRegime } from "@/lib/api";

// --- fixtures -------------------------------------------------------------
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
      vix_elevated: false,
      term_inversion: false,
      credit_widening: true,
      safe_haven_bid: false,
      breadth_deterioration: false,
    },
    raw: {},
    summary: "calm tape",
    available: true,
    ...over,
  } as StressRegime & { available?: boolean };
}

// Visible text only — strip tags so class names never trip word checks.
const visibleText = (html: string) => html.replace(/<[^>]*>/g, " ").toLowerCase();

describe("selectFiringFundingModes", () => {
  it("returns only fired modes, most-severe first, drivers verbatim", () => {
    const out = selectFiringFundingModes(
      funding({
        modes: {
          credit_widening: { fired: true, severity: "mild", drivers: ["HYG -0.59%/5d"], rationale: "" },
          dollar_shortage: { fired: true, severity: "elevated", drivers: ["DXY +1.17%/5d"], rationale: "" },
          duration_shock: { fired: false, severity: "none", drivers: [], rationale: "" },
        },
      } as Partial<FundingStressMode>),
    );
    expect(out.map((m) => m.mode)).toEqual(["dollar_shortage", "credit_widening"]);
    expect(out[0]!.drivers).toEqual(["DXY +1.17%/5d"]);
    expect(out[0]!.severity).toBe("elevated");
  });

  it("returns [] when unavailable or nothing fired", () => {
    expect(selectFiringFundingModes(null)).toEqual([]);
    expect(selectFiringFundingModes(funding({ available: false }))).toEqual([]);
    expect(
      selectFiringFundingModes(
        funding({ modes: { duration_shock: { fired: false, severity: "none", drivers: [], rationale: "" } } } as Partial<FundingStressMode>),
      ),
    ).toEqual([]);
  });

  it("does not invent drivers when a fired mode has none", () => {
    const out = selectFiringFundingModes(
      funding({ modes: { dollar_shortage: { fired: true, severity: "elevated", drivers: [], rationale: "" } } } as Partial<FundingStressMode>),
    );
    expect(out[0]!.drivers).toEqual([]);
  });
});

describe("selectFiringStressSignals", () => {
  it("returns labels of firing component flags only, canonical order", () => {
    const out = selectFiringStressSignals(
      stress({
        signals: {
          vix_elevated: true,
          term_inversion: false,
          credit_widening: true,
          safe_haven_bid: false,
          breadth_deterioration: false,
        },
      } as Partial<StressRegime>),
    );
    expect(out.map((s) => s.label)).toEqual(["VIX elevated", "Credit widening"]);
  });

  it("returns [] when the signals block is absent", () => {
    expect(selectFiringStressSignals(null)).toEqual([]);
    expect(selectFiringStressSignals(stress({ signals: undefined } as Partial<StressRegime>))).toEqual([]);
  });
});

describe("selectCreditConfirmation", () => {
  it("returns label + differential when available", () => {
    expect(
      selectCreditConfirmation({ available: true, regime_label: "Rates-driven bond weakness", hy_ig_differential_5d: 0.12 }),
    ).toEqual({ label: "Rates-driven bond weakness", diff: 0.12 });
  });

  it("returns null when unavailable or unlabeled", () => {
    expect(selectCreditConfirmation(null)).toBeNull();
    expect(selectCreditConfirmation({ available: false, regime_label: "x" })).toBeNull();
    expect(selectCreditConfirmation({ available: true, regime_label: "   " })).toBeNull();
  });
});

describe("horizon discipline copy", () => {
  it("uses the exact required note + plain meaning", () => {
    expect(HORIZON_DISCIPLINE_NOTE).toBe(
      "Second-order reads are short- and medium-horizon event claims, not permanent asset forecasts.",
    );
    expect(HORIZON_DISCIPLINE_PLAIN).toBe(
      "A headline can move oil, rates, credit, or equities for days or weeks without changing the long-run trend.",
    );
  });

  it("includes 1d/5d/20d horizons and a secular baseline explicitly outside the event claim", () => {
    const ks = HORIZON_ROWS.map((h) => h.k);
    expect(ks).toContain("1d");
    expect(ks).toContain("5d");
    expect(ks).toContain("20d");
    const secular = HORIZON_ROWS.find((h) => h.k.toLowerCase().includes("secular"));
    expect(secular).toBeTruthy();
    expect(`${secular!.label} ${secular!.note}`.toLowerCase()).toContain("outside this event claim");
  });
});

describe("UncertaintyCard render", () => {
  const baseProps = {
    stress: stress(),
    funding: funding(),
    creditRegime: { available: true, regime_label: "Rates-driven bond weakness", hy_ig_differential_5d: 0.12 },
    explanation: {
      meaning: "Composite cross-asset stress regime across volatility, credit, and breadth.",
      what_changes_it: "VIX falling back below its 20d average, credit spreads tightening.",
    },
  };

  it("renders the firing funding driver text driver-first", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...baseProps} />);
    expect(html).toContain("DXY +1.17%/5d");
  });

  it("renders the horizon-discipline block (note, plain meaning, first repricing)", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...baseProps} />);
    expect(html).toContain(HORIZON_DISCIPLINE_NOTE);
    expect(html).toContain(HORIZON_DISCIPLINE_PLAIN);
    expect(html).toContain("first repricing");
  });

  it("renders what_changes_it under a descriptive label when supplied", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...baseProps} />);
    expect(html).toContain(INTERPRETATION_WHAT_CHANGES_LABEL);
    expect(html).toContain("credit spreads tightening");
  });

  it("omits the what-would-change line when not supplied (no invented content)", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...baseProps} explanation={{ meaning: "m" }} />);
    expect(html).not.toContain(INTERPRETATION_WHAT_CHANGES_LABEL);
  });

  it("does not render non-fired modes", () => {
    const html = renderToStaticMarkup(<UncertaintyCard {...baseProps} />);
    expect(visibleText(html)).not.toContain("duration shock");
  });

  it("carries none of the banned overclaim / trading words in visible text", () => {
    const text = visibleText(renderToStaticMarkup(<UncertaintyCard {...baseProps} />));
    for (const w of ["buy", "sell", "alpha", "signal", "proof", "proves"]) {
      expect(text).not.toContain(w);
    }
  });
});
