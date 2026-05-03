/**
 * Tests for macro section degraded-state derivation.
 */

import { describe, it, expect } from "vitest";
import {
  deriveStressDegraded,
  deriveRatesDegraded,
  deriveIndicatorDegraded,
} from "../macro-degraded";
import type { StressRegime, RatesContext, StressComponentDetail } from "../api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fullStress(): StressRegime {
  return {
    regime: "Calm",
    signals: {
      vix_elevated: false,
      term_inversion: false,
      credit_widening: false,
      safe_haven_bid: false,
      breadth_deterioration: false,
    },
    raw: {},
    detail: {
      volatility: { label: "Volatility", status: "calm", explanation: "ok", value: 15.2, avg20: 14.5, change_5d: -0.3 },
      term_structure: { label: "Term Structure", status: "calm", explanation: "ok", value: 15.2, vix3m: 16.0 },
      credit: { label: "Credit Stress", status: "calm", explanation: "ok", spread_5d: 0.1 },
      safe_haven: { label: "Safe Haven", status: "calm", explanation: "ok", inflow_count: 1 },
      breadth: { label: "Breadth", status: "calm", explanation: "ok", gap_5d: -0.2 },
    },
    summary: "All calm",
  };
}

function fullRates(): RatesContext {
  return {
    regime: "Mixed",
    nominal: { label: "10Y yield", value: 4.35, change_5d: 0.05 },
    real_proxy: { label: "TIP", value: 110.0, change_5d: -0.3 },
    breakeven_proxy: { label: "BE", value: null, change_5d: -0.1 },
    raw: {},
  };
}

// ---------------------------------------------------------------------------
// deriveStressDegraded
// ---------------------------------------------------------------------------

describe("deriveStressDegraded", () => {
  it("null stress → unavailable", () => {
    expect(deriveStressDegraded(null)).toBe("Stress data unavailable");
  });

  it("undefined stress → unavailable", () => {
    expect(deriveStressDegraded(undefined)).toBe("Stress data unavailable");
  });

  it("healthy stress → null (no warning)", () => {
    expect(deriveStressDegraded(fullStress())).toBeNull();
  });

  it("all detail values null → all missing", () => {
    const s = fullStress();
    for (const k of Object.keys(s.detail!)) {
      const d = s.detail![k]!;
      d.value = null;
      d.avg20 = null;
      d.change_5d = null;
      d.spread_5d = null;
      d.gap_5d = null;
      d.inflow_count = undefined;
    }
    expect(deriveStressDegraded(s)).toBe("All stress values missing");
  });

  it("some detail values null → partial", () => {
    const s = fullStress();
    // Null out volatility and term_structure
    s.detail!.volatility!.value = null;
    s.detail!.volatility!.avg20 = null;
    s.detail!.volatility!.change_5d = null;
    s.detail!.term_structure!.value = null;
    s.detail!.term_structure!.vix3m = null;
    const result = deriveStressDegraded(s);
    expect(result).toContain("of 5 stress signals partial");
  });

  it("empty detail object → all signals unavailable", () => {
    const s = fullStress();
    s.detail = {};
    expect(deriveStressDegraded(s)).toBe("All stress signals unavailable");
  });
});

// ---------------------------------------------------------------------------
// deriveRatesDegraded
// ---------------------------------------------------------------------------

describe("deriveRatesDegraded", () => {
  it("null rates → unavailable", () => {
    expect(deriveRatesDegraded(null)).toBe("Rates data unavailable");
  });

  it("healthy rates → null", () => {
    expect(deriveRatesDegraded(fullRates())).toBeNull();
  });

  it("all entries null → all missing", () => {
    const r = fullRates();
    r.nominal = { label: "10Y", value: null, change_5d: null };
    r.real_proxy = { label: "TIP", value: null, change_5d: null };
    r.breakeven_proxy = { label: "BE", value: null, change_5d: null };
    expect(deriveRatesDegraded(r)).toBe("All rates data missing");
  });

  it("one entry missing → partial", () => {
    const r = fullRates();
    r.nominal = { label: "10Y", value: null, change_5d: null };
    const result = deriveRatesDegraded(r);
    expect(result).toBe("1 of 3 rate metrics missing");
  });

  it("value present but change null → still healthy", () => {
    const r = fullRates();
    r.nominal = { label: "10Y", value: 4.35, change_5d: null };
    expect(deriveRatesDegraded(r)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// deriveIndicatorDegraded
// ---------------------------------------------------------------------------

describe("deriveIndicatorDegraded", () => {
  it("indicator with value → null (healthy)", () => {
    const d: StressComponentDetail = {
      label: "Volatility", status: "calm", explanation: "ok",
      value: 15.2,
    };
    expect(deriveIndicatorDegraded(d)).toBeNull();
  });

  it("indicator with only spread_5d → healthy", () => {
    const d: StressComponentDetail = {
      label: "Credit", status: "calm", explanation: "ok",
      spread_5d: 0.1,
    };
    expect(deriveIndicatorDegraded(d)).toBeNull();
  });

  it("indicator with only inflow_count → healthy", () => {
    const d: StressComponentDetail = {
      label: "Safe Haven", status: "calm", explanation: "ok",
      inflow_count: 2,
    };
    expect(deriveIndicatorDegraded(d)).toBeNull();
  });

  it("indicator with all null → degraded", () => {
    const d: StressComponentDetail = {
      label: "Volatility", status: "calm", explanation: "VIX unavailable",
    };
    expect(deriveIndicatorDegraded(d)).toBe("Data unavailable");
  });

  it("indicator with explicit null value → degraded", () => {
    const d: StressComponentDetail = {
      label: "Volatility", status: "calm", explanation: "VIX unavailable",
      value: null, change_5d: null,
    };
    expect(deriveIndicatorDegraded(d)).toBe("Data unavailable");
  });
});
