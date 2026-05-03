import { describe, it, expect } from "vitest";
import { deriveDegradedNotice, deriveContextDegradedNotice, type DegradedNotice } from "../degraded-data-notice";
import type { MarketResult, AnalysisDetail, MarketContext } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function minimalMarket(overrides?: Partial<MarketResult>): MarketResult {
  return {
    note: "OK",
    details: {},
    tickers: [
      { symbol: "XOM", role: "beneficiary", label: "oil", direction_tag: null,
        return_1d: 0.5, return_5d: 2.1, return_20d: 4.3, volume_ratio: 1.2,
        vs_xle_5d: null, spark: [100, 101] },
    ],
    ...overrides,
  };
}

function minimalAnalysis(overrides?: Partial<AnalysisDetail>): AnalysisDetail {
  return {
    what_changed: "X",
    mechanism_summary: "Y",
    beneficiaries: [],
    losers: [],
    beneficiary_tickers: [],
    loser_tickers: [],
    assets_to_watch: [],
    confidence: "medium",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 1. Returns null when healthy
// ---------------------------------------------------------------------------

describe("deriveDegradedNotice — healthy", () => {
  it("returns null for healthy market + analysis", () => {
    expect(deriveDegradedNotice(minimalMarket(), minimalAnalysis())).toBeNull();
  });

  it("returns null when both args are null", () => {
    expect(deriveDegradedNotice(null, null)).toBeNull();
  });

  it("returns null when both args are undefined", () => {
    expect(deriveDegradedNotice()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2. Priority 1 — market data_quality degraded
// ---------------------------------------------------------------------------

describe("deriveDegradedNotice — market degraded", () => {
  it("fires warn when data_quality is degraded", () => {
    const n = deriveDegradedNotice(
      minimalMarket({ data_quality: "degraded", data_quality_note: "Stale tickers" }),
    );
    expect(n).not.toBeNull();
    expect(n!.severity).toBe("warn");
    expect(n!.label).toBe("Partial market data");
    expect(n!.detail).toBe("Stale tickers");
  });

  it("detail is null when note missing", () => {
    const n = deriveDegradedNotice(minimalMarket({ data_quality: "degraded" }));
    expect(n!.detail).toBeNull();
  });

  it("does not fire when data_quality is ok", () => {
    expect(deriveDegradedNotice(minimalMarket({ data_quality: "ok" }))).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. Priority 2 — analysis degraded flag
// ---------------------------------------------------------------------------

describe("deriveDegradedNotice — analysis degraded", () => {
  it("fires info with single validation warning", () => {
    const n = deriveDegradedNotice(
      minimalMarket(),
      minimalAnalysis({ degraded: true, validation_warnings: ["stale XOM"] }),
    );
    expect(n!.severity).toBe("info");
    expect(n!.label).toBe("Partial analysis");
    expect(n!.detail).toBe("stale XOM");
  });

  it("fires info with count for multiple warnings", () => {
    const n = deriveDegradedNotice(
      minimalMarket(),
      minimalAnalysis({ degraded: true, validation_warnings: ["a", "b", "c"] }),
    );
    expect(n!.detail).toBe("3 validation issues");
  });

  it("detail null when degraded but no warnings", () => {
    const n = deriveDegradedNotice(
      minimalMarket(),
      minimalAnalysis({ degraded: true }),
    );
    expect(n!.detail).toBeNull();
  });

  it("market degraded takes priority over analysis degraded", () => {
    const n = deriveDegradedNotice(
      minimalMarket({ data_quality: "degraded" }),
      minimalAnalysis({ degraded: true, validation_warnings: ["x"] }),
    );
    expect(n!.label).toBe("Partial market data");
  });
});

// ---------------------------------------------------------------------------
// 4. Priority 3 — validation warnings without degraded flag
// ---------------------------------------------------------------------------

describe("deriveDegradedNotice — warnings only", () => {
  it("fires info for lone warning", () => {
    const n = deriveDegradedNotice(
      minimalMarket(),
      minimalAnalysis({ validation_warnings: ["ticker AAL stale"] }),
    );
    expect(n!.severity).toBe("info");
    expect(n!.label).toBe("Data caveats");
    expect(n!.detail).toBe("ticker AAL stale");
  });

  it("fires info with count for multiple warnings", () => {
    const n = deriveDegradedNotice(
      minimalMarket(),
      minimalAnalysis({ validation_warnings: ["a", "b"] }),
    );
    expect(n!.detail).toBe("2 items");
  });

  it("does not fire for empty warnings array", () => {
    expect(
      deriveDegradedNotice(minimalMarket(), minimalAnalysis({ validation_warnings: [] })),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 5. Priority 4 — all tickers lack return data
// ---------------------------------------------------------------------------

describe("deriveDegradedNotice — no ticker data", () => {
  it("fires warn when all tickers have null return_5d", () => {
    const market = minimalMarket({
      tickers: [
        { symbol: "X", role: "beneficiary", label: "x", direction_tag: null,
          return_1d: null, return_5d: null, return_20d: null, volume_ratio: null,
          vs_xle_5d: null, spark: [] },
      ],
    });
    const n = deriveDegradedNotice(market);
    expect(n!.severity).toBe("warn");
    expect(n!.label).toBe("No ticker data");
  });

  it("fires warn when all tickers have label 'needs more evidence'", () => {
    const market = minimalMarket({
      tickers: [
        { symbol: "X", role: "beneficiary", label: "needs more evidence",
          direction_tag: null, return_1d: 0.5, return_5d: 1.0, return_20d: 2.0,
          volume_ratio: 1.0, vs_xle_5d: null, spark: [] },
      ],
    });
    const n = deriveDegradedNotice(market);
    expect(n!.severity).toBe("warn");
    expect(n!.label).toBe("No ticker data");
  });

  it("does not fire when at least one ticker has return data", () => {
    expect(deriveDegradedNotice(minimalMarket())).toBeNull();
  });

  it("does not fire for empty tickers array", () => {
    expect(deriveDegradedNotice(minimalMarket({ tickers: [] }))).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 6. Context variant — deriveContextDegradedNotice
// ---------------------------------------------------------------------------

function minimalContext(overrides?: Partial<MarketContext>): MarketContext {
  return {
    built_at: "2026-04-12T12:00:00Z",
    source: "yfinance",
    snapshots: [],
    snapshots_meta: { total: 10, fresh: 10, stale: 0, unavailable: 0 },
    stress: { regime: "Unknown", signals: {} as any, raw: {}, available: true },
    rates: { regime: "Unknown", nominal: { label: "US10Y" }, real_proxy: { label: "TIP" }, breakeven_proxy: { label: "BE10Y" }, raw: {}, available: true },
    regime_vector: { inflation: "unknown", policy_stance: "unknown", fx: "unknown", growth_stress: "unknown", available: true },
    highlights: [],
    highlights_meta: { count: 0, source: "movers/today" },
    ...overrides,
  } as MarketContext;
}

describe("deriveContextDegradedNotice — healthy", () => {
  it("returns null for healthy context", () => {
    expect(deriveContextDegradedNotice(minimalContext())).toBeNull();
  });

  it("returns null for null/undefined", () => {
    expect(deriveContextDegradedNotice(null)).toBeNull();
    expect(deriveContextDegradedNotice()).toBeNull();
  });
});

describe("deriveContextDegradedNotice — provider issues", () => {
  it("fires warn when majority unavailable", () => {
    const n = deriveContextDegradedNotice(
      minimalContext({ snapshots_meta: { total: 10, fresh: 2, stale: 2, unavailable: 6 } }),
    );
    expect(n!.severity).toBe("warn");
    expect(n!.label).toBe("Provider issues");
    expect(n!.detail).toContain("6/10");
  });
});

describe("deriveContextDegradedNotice — stale snapshots", () => {
  it("fires info when majority stale", () => {
    const n = deriveContextDegradedNotice(
      minimalContext({ snapshots_meta: { total: 10, fresh: 3, stale: 7, unavailable: 0 } }),
    );
    expect(n!.severity).toBe("info");
    expect(n!.label).toBe("Stale snapshots");
  });

  it("does not fire when minority stale", () => {
    expect(
      deriveContextDegradedNotice(
        minimalContext({ snapshots_meta: { total: 10, fresh: 8, stale: 2, unavailable: 0 } }),
      ),
    ).toBeNull();
  });
});

describe("deriveContextDegradedNotice — limited context", () => {
  it("fires info when both stress and rates unavailable", () => {
    const n = deriveContextDegradedNotice(
      minimalContext({
        stress: { regime: "Unknown", signals: {} as any, raw: {}, available: false },
        rates: { regime: "Unknown", nominal: { label: "US10Y" }, real_proxy: { label: "TIP" }, breakeven_proxy: { label: "BE10Y" }, raw: {}, available: false },
      } as any),
    );
    expect(n!.severity).toBe("info");
    expect(n!.label).toBe("Limited context");
  });

  it("does not fire when only one is unavailable", () => {
    expect(
      deriveContextDegradedNotice(
        minimalContext({
          stress: { regime: "Unknown", signals: {} as any, raw: {}, available: false },
        } as any),
      ),
    ).toBeNull();
  });
});
