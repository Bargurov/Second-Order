import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { formatMemo, formatBlurb } from "../format-memo";
import type { AnalyzeResponse, AnalysisDetail, MarketResult, Ticker } from "../api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTicker(overrides?: Partial<Ticker>): Ticker {
  return {
    symbol: "XOM",
    role: "beneficiary",
    label: "oil",
    direction_tag: "supports ↑",
    return_1d: 0.5,
    return_5d: 2.1,
    return_20d: 4.3,
    volume_ratio: 1.2,
    vs_xle_5d: null,
    spark: [100, 101, 102],
    ...overrides,
  };
}

function makeAnalysis(overrides?: Partial<AnalysisDetail>): AnalysisDetail {
  return {
    what_changed: "OPEC cut output.",
    mechanism_summary: "Supply reduction raises oil prices.",
    beneficiaries: ["Oil majors"],
    losers: ["Airlines"],
    beneficiary_tickers: ["XOM"],
    loser_tickers: ["AAL"],
    assets_to_watch: ["CL=F"],
    confidence: "medium",
    ...overrides,
  };
}

function makeMarket(overrides?: Partial<MarketResult>): MarketResult {
  return {
    note: "Market data from yfinance.",
    details: {},
    tickers: [
      makeTicker(),
      makeTicker({ symbol: "AAL", role: "loser", return_5d: -3.2, return_20d: -5.1, volume_ratio: 0.8, direction_tag: "pressures ↓" }),
    ],
    ...overrides,
  };
}

function makeResponse(overrides?: Partial<AnalyzeResponse>): AnalyzeResponse {
  return {
    headline: "OPEC cuts output",
    stage: "developing",
    persistence: "1w",
    analysis: makeAnalysis(),
    market: makeMarket(),
    is_mock: false,
    event_date: "2026-04-10",
    ...overrides,
  };
}

// Freeze Date.now for stable timestamp assertions
let dateSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  dateSpy = vi.spyOn(Date.prototype, "toISOString").mockReturnValue("2026-04-12T14:30:00.000Z");
});
afterEach(() => {
  dateSpy.mockRestore();
});

// ═══════════════════════════════════════════════════════════════════════════
// formatMemo
// ═══════════════════════════════════════════════════════════════════════════

describe("formatMemo — header", () => {
  it("includes headline and date", () => {
    const out = formatMemo(makeResponse());
    expect(out).toContain("SECOND ORDER — RESEARCH NOTE");
    expect(out).toContain("Event:  OPEC cuts output");
    expect(out).toContain("Date:   2026-04-10");
  });

  it("compact metadata line contains stage + persistence + confidence", () => {
    const out = formatMemo(makeResponse());
    expect(out).toContain("Status: developing  ·  1w  ·  medium confidence");
  });

  it("includes freshness when provided", () => {
    const out = formatMemo(makeResponse({
      freshness: { bucket: "warm", natural_bucket: "warm", event_age_days: 3, is_frozen: false, force_bypassed: false },
    }));
    expect(out).toContain("Fresh:  warm (3d old)");
  });

  it("shows frozen flag in freshness", () => {
    const out = formatMemo(makeResponse({
      freshness: { bucket: "frozen", natural_bucket: "frozen", event_age_days: 45, is_frozen: true, force_bypassed: false },
    }));
    expect(out).toContain("frozen (45d old) · frozen");
  });
});

describe("formatMemo — core sections", () => {
  it("includes WHAT CHANGED and MECHANISM", () => {
    const out = formatMemo(makeResponse());
    expect(out).toContain("WHAT CHANGED");
    expect(out).toContain("OPEC cut output.");
    expect(out).toContain("SECOND-ORDER MECHANISM");
    expect(out).toContain("Supply reduction raises oil prices.");
  });

  it("includes AFFECTED ASSETS", () => {
    const out = formatMemo(makeResponse());
    expect(out).toContain("AFFECTED ASSETS");
    expect(out).toContain("Beneficiaries : Oil majors");
    expect(out).toContain("Losers        : Airlines");
    expect(out).toContain("Watch         : CL=F");
  });

  it("includes transmission chain", () => {
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({ transmission_chain: ["OPEC cut", "supply drop", "price rise"] }),
    }));
    expect(out).toContain("TRANSMISSION");
    expect(out).toContain("OPEC cut → supply drop → price rise");
  });
});

describe("formatMemo — overlay sections", () => {
  it("includes SHOCK CHANNELS when available", () => {
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({
        shock_decomposition: {
          primary: "commodity",
          primary_label: "Commodity channel",
          rationale: "Oil is the dominant shock vector",
          available: true,
          stale: false,
        } as any,
      }),
    }));
    expect(out).toContain("SHOCK CHANNELS");
    expect(out).toContain("Primary: Commodity channel — Oil is the dominant shock vector");
  });

  it("omits SHOCK CHANNELS when available is false", () => {
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({
        shock_decomposition: {
          primary_label: "Commodity",
          available: false,
        } as any,
      }),
    }));
    expect(out).not.toContain("SHOCK CHANNELS");
  });

  it("omits SHOCK CHANNELS when stale", () => {
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({
        shock_decomposition: {
          primary_label: "Commodity",
          available: true,
          stale: true,
        } as any,
      }),
    }));
    expect(out).not.toContain("SHOCK CHANNELS");
  });

  it("includes REACTION FUNCTION when available", () => {
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({
        reaction_function_divergence: {
          implied: "hawkish",
          implied_label: "Hawkish",
          priced: "dovish",
          priced_label: "Dovish",
          divergence: "sharp",
          divergence_label: "Sharp divergence",
          rationale: "Market expects rate cuts but Fed is hiking",
          available: true,
          stale: false,
        } as any,
      }),
    }));
    expect(out).toContain("REACTION FUNCTION");
    expect(out).toContain("Implied: Hawkish");
    expect(out).toContain("Priced: Dovish");
    expect(out).toContain("Sharp divergence");
    expect(out).toContain("Market expects rate cuts but Fed is hiking");
  });

  it("omits REACTION FUNCTION when unavailable", () => {
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({
        reaction_function_divergence: {
          implied_label: "Hawkish",
          available: false,
        } as any,
      }),
    }));
    expect(out).not.toContain("REACTION FUNCTION");
  });

  it("includes HISTORICAL ANALOGS (max 3)", () => {
    const analogs = [
      { headline: "1990 Iraq invasion", event_date: "1990-08-02", stage: "developing", persistence: "3m", confidence: "high", return_5d: 5.0, return_20d: 12.0, decay: "Accelerating" },
      { headline: "2014 OPEC price war", event_date: "2014-11-27", stage: "mature", persistence: "6m", confidence: "high", return_5d: -8.0, return_20d: -20.0, decay: "Fading" },
    ];
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({ historical_analogs: analogs } as any),
    }));
    expect(out).toContain("HISTORICAL ANALOGS");
    expect(out).toContain("1990 Iraq invasion (1990-08-02) — Accelerating");
    expect(out).toContain("2014 OPEC price war (2014-11-27) — Fading");
  });

  it("caps analogs at 3", () => {
    const analogs = Array.from({ length: 5 }, (_, i) => ({
      headline: `Analog ${i}`, event_date: "2020-01-01", stage: "x", persistence: "x",
      confidence: "x", return_5d: 1, return_20d: 2, decay: "Holding",
    }));
    const out = formatMemo(makeResponse({
      analysis: makeAnalysis({ historical_analogs: analogs } as any),
    }));
    expect(out).toContain("Analog 0");
    expect(out).toContain("Analog 2");
    expect(out).not.toContain("Analog 3");
  });
});

describe("formatMemo — ticker table", () => {
  it("includes 20d and Vol columns", () => {
    const out = formatMemo(makeResponse());
    // Header row
    expect(out).toContain("20d");
    expect(out).toContain("Vol");
    // Data row for XOM
    expect(out).toContain("+4.30%");   // 20d
    expect(out).toContain("1.2x");     // vol
  });

  it("handles null returns and volume gracefully", () => {
    const out = formatMemo(makeResponse({
      market: makeMarket({
        tickers: [makeTicker({ return_20d: null, volume_ratio: null })],
      }),
    }));
    expect(out).toContain("—"); // null placeholders
  });
});

describe("formatMemo — footer", () => {
  it("includes timestamp", () => {
    const out = formatMemo(makeResponse());
    expect(out).toContain("Generated 2026-04-12 14:30 UTC");
  });

  it("includes data quality warning when degraded", () => {
    const out = formatMemo(makeResponse({
      market: makeMarket({ data_quality: "degraded", data_quality_note: "Stale tickers detected" }),
    }));
    expect(out).toContain("⚠ Stale tickers detected");
  });

  it("omits data quality warning when OK", () => {
    const out = formatMemo(makeResponse({
      market: makeMarket({ data_quality: "ok" }),
    }));
    expect(out).not.toContain("⚠");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// formatBlurb
// ═══════════════════════════════════════════════════════════════════════════

describe("formatBlurb — structure", () => {
  it("starts with headline + stage + confidence", () => {
    const out = formatBlurb(makeResponse());
    const first = out.split("\n")[0];
    expect(first).toContain("OPEC cuts output");
    expect(first).toContain("developing");
    expect(first).toContain("medium confidence");
  });

  it("includes mechanism line", () => {
    const out = formatBlurb(makeResponse());
    expect(out).toContain("Mechanism: Supply reduction raises oil prices.");
  });

  it("truncates long mechanism at 120 chars", () => {
    const longMech = "A".repeat(200);
    const out = formatBlurb(makeResponse({
      analysis: makeAnalysis({ mechanism_summary: longMech }),
    }));
    const mechLine = out.split("\n").find((l) => l.startsWith("Mechanism:"))!;
    // "Mechanism: " is 11 chars, content should be 119 chars + "…"
    expect(mechLine.length).toBeLessThanOrEqual(11 + 120);
    expect(mechLine).toContain("…");
  });

  it("includes beneficiary tickers with ▲", () => {
    const out = formatBlurb(makeResponse());
    expect(out).toContain("▲ XOM +2.10%");
  });

  it("includes loser tickers with ▼", () => {
    const out = formatBlurb(makeResponse());
    expect(out).toContain("▼ AAL -3.20%");
  });

  it("omits ticker line when no tickers have return data", () => {
    const out = formatBlurb(makeResponse({
      market: makeMarket({ tickers: [] }),
    }));
    expect(out).not.toContain("▲");
    expect(out).not.toContain("▼");
  });

  it("caps tickers at 3 per side", () => {
    const bens = Array.from({ length: 5 }, (_, i) =>
      makeTicker({ symbol: `B${i}`, role: "beneficiary", return_5d: i + 1 }),
    );
    const out = formatBlurb(makeResponse({
      market: makeMarket({ tickers: bens }),
    }));
    // Should have at most 3 tickers in the ▲ section
    const tickerLine = out.split("\n").find((l) => l.includes("▲"))!;
    const count = tickerLine.split(",").length;
    expect(count).toBeLessThanOrEqual(3);
  });

  it("includes timestamp", () => {
    const out = formatBlurb(makeResponse());
    expect(out).toContain("Generated 2026-04-12 14:30 UTC");
  });

  it("is compact — 3 to 5 lines", () => {
    const out = formatBlurb(makeResponse());
    const lineCount = out.split("\n").length;
    expect(lineCount).toBeGreaterThanOrEqual(3);
    expect(lineCount).toBeLessThanOrEqual(5);
  });
});
