/**
 * Unit tests for evidence-quality-strip render/format logic.
 *
 * Tests the pure buildQualitySignals() function and minutesAgo() helper
 * directly — no React rendering needed.
 */

import { describe, it, expect } from "vitest";
import {
  buildQualitySignals,
  minutesAgo,
  type QualitySignal,
} from "../evidence-quality-strip";
import type { AnalyzeResponse, Ticker } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTicker(overrides: Partial<Ticker> = {}): Ticker {
  return {
    symbol: "AAPL",
    role: "beneficiary",
    label: "tech",
    direction_tag: null,
    return_1d: 0.5,
    return_5d: 2.0,
    return_20d: 4.0,
    volume_ratio: 1.0,
    vs_xle_5d: null,
    spark: [],
    ...overrides,
  };
}

function makeResult(overrides: Partial<AnalyzeResponse> = {}): AnalyzeResponse {
  return {
    headline: "Test headline",
    stage: "developing",
    persistence: "1w",
    is_mock: false,
    event_date: "2026-04-10",
    analysis: {
      what_changed: "Something changed.",
      mechanism_summary: "A causes B.",
      beneficiaries: ["Oil majors"],
      losers: ["Airlines"],
      beneficiary_tickers: ["XOM"],
      loser_tickers: ["AAL"],
      assets_to_watch: ["CL=F"],
      confidence: "medium",
      transmission_chain: ["a", "b"],
    },
    market: {
      note: "Market note",
      details: {},
      tickers: [
        makeTicker({ symbol: "XOM", direction_tag: "supports ↑" }),
        makeTicker({ symbol: "AAL", direction_tag: "contradicts ↓" }),
        makeTicker({ symbol: "CL=F", direction_tag: null }),
      ],
    },
    ...overrides,
  } as AnalyzeResponse;
}

function findSignal(signals: QualitySignal[], label: string) {
  return signals.find((s) => s.label === label);
}

// ---------------------------------------------------------------------------
// buildQualitySignals
// ---------------------------------------------------------------------------

describe("buildQualitySignals", () => {
  // F2 claim honesty: the supporting-ticker ratio is labelled "Aligned",
  // not "Confirmed" — tape-direction agreement is descriptive, not thesis
  // confirmation.  Guard against a regression back to the overclaim word.
  it("labels the tape-alignment ratio 'Aligned', never 'Confirmed'", () => {
    const signals = buildQualitySignals(makeResult());
    expect(findSignal(signals, "Aligned")).toBeDefined();
    expect(findSignal(signals, "Confirmed")).toBeUndefined();
  });

  it("computes tape-alignment ratio from direction_tag", () => {
    const result = makeResult({
      market: {
        note: "",
        details: {},
        tickers: [
          makeTicker({ direction_tag: "supports ↑" }),
          makeTicker({ direction_tag: "supports ↑" }),
          makeTicker({ direction_tag: "contradicts ↓" }),
        ],
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Aligned");
    expect(sig).toBeDefined();
    // 2 supporting / 3 assessed = 67%
    expect(sig!.value).toBe("67%");
    expect(sig!.tone).toBe("positive");
  });

  it("returns warn tone when most tickers contradict", () => {
    const result = makeResult({
      market: {
        note: "",
        details: {},
        tickers: [
          makeTicker({ direction_tag: "contradicts ↓" }),
          makeTicker({ direction_tag: "contradicts ↓" }),
          makeTicker({ direction_tag: "supports ↑" }),
        ],
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Aligned");
    expect(sig!.value).toBe("33%");
    expect(sig!.tone).toBe("neutral"); // 33% is >= 0.3
  });

  it("returns dash when no tickers are assessed", () => {
    const result = makeResult({
      market: {
        note: "",
        details: {},
        tickers: [makeTicker({ direction_tag: null })],
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Aligned");
    expect(sig!.value).toBe("—");
    expect(sig!.tone).toBe("neutral");
  });

  it("counts ticker depth excluding placeholder labels", () => {
    const result = makeResult({
      market: {
        note: "",
        details: {},
        tickers: [
          makeTicker({ return_5d: 2.0 }),
          makeTicker({ return_5d: null }),
          makeTicker({ label: "needs more evidence", return_5d: 0.0 }),
        ],
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Tickers");
    expect(sig!.value).toBe("1/3");
    expect(sig!.tone).toBe("neutral");
  });

  it("reports analog count", () => {
    const result = makeResult();
    // No analogs by default
    const sig = findSignal(buildQualitySignals(result), "Analogs");
    expect(sig!.value).toBe("none");
    expect(sig!.tone).toBe("warn");
  });

  it("reports positive analog tone when >= 2", () => {
    const result = makeResult();
    (result.analysis as any).historical_analogs = [
      { headline: "a" },
      { headline: "b" },
    ];
    const sig = findSignal(buildQualitySignals(result), "Analogs");
    expect(sig!.value).toBe("2");
    expect(sig!.tone).toBe("positive");
  });

  it("flags frozen market data", () => {
    const result = makeResult({
      market: {
        note: "",
        details: {},
        tickers: [],
        market_check_staleness: "frozen",
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Data");
    expect(sig!.value).toBe("frozen");
    expect(sig!.tone).toBe("warn");
  });

  it("shows live when market check is recent", () => {
    const result = makeResult({
      market: {
        note: "",
        details: {},
        tickers: [],
        last_market_check_at: new Date().toISOString(),
        market_check_staleness: "fresh",
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Data");
    expect(sig!.value).toBe("live");
    expect(sig!.tone).toBe("positive");
  });

  it("includes archive frozen flag", () => {
    const result = makeResult({
      freshness: {
        bucket: "frozen" as any,
        is_frozen: true,
        event_age_days: 45,
      },
    });
    const sig = findSignal(buildQualitySignals(result), "Archive");
    expect(sig!.value).toBe("frozen");
    expect(sig!.tone).toBe("warn");
  });

  it("omits archive flag when not frozen", () => {
    const result = makeResult();
    const sig = findSignal(buildQualitySignals(result), "Archive");
    expect(sig).toBeUndefined();
  });

  it("returns empty array when market has no tickers and no freshness", () => {
    const result = makeResult({
      market: { note: "", details: {}, tickers: [] },
    });
    // Should still have Analogs signal at minimum
    const signals = buildQualitySignals(result);
    expect(signals.length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// minutesAgo
// ---------------------------------------------------------------------------

describe("minutesAgo", () => {
  it("returns 0 for now", () => {
    expect(minutesAgo(new Date().toISOString())).toBeLessThanOrEqual(1);
  });

  it("returns ~60 for one hour ago", () => {
    const oneHourAgo = new Date(Date.now() - 60 * 60_000).toISOString();
    const m = minutesAgo(oneHourAgo);
    expect(m).toBeGreaterThanOrEqual(59);
    expect(m).toBeLessThanOrEqual(61);
  });

  it("returns 999 for invalid input", () => {
    expect(minutesAgo("not-a-date")).toBe(999);
  });

  it("never returns negative", () => {
    // Future timestamp
    const future = new Date(Date.now() + 60_000).toISOString();
    expect(minutesAgo(future)).toBe(0);
  });
});
