/**
 * Contract tests — verify frontend type assumptions match backend reality.
 *
 * These tests use compile-time type assertions and runtime shape checks
 * against representative payloads so type drift is caught early.
 */

import { describe, it, expect } from "vitest";
import {
  _buildNewsPath,
  _buildPortfolioPath,
  hasActivePortfolioFilters,
  isPortfolioEnvelope,
  unwrapPortfolioItems,
} from "../api";
import type {
  AnalyzeResponse,
  AnalysisDetail,
  Confidence,
  Ticker,
  MarketResult,
  FreshnessBlock,
  FreshnessBucket,
  MarketMover,
  MoverTicker,
  MarketContext,
  TrackRecord,
  PortfolioEntry,
  PortfolioFilters,
  PortfolioFilteredResponse,
} from "../api";

// ---------------------------------------------------------------------------
// Helpers: minimal valid payloads matching backend output
// ---------------------------------------------------------------------------

function makeMinimalTicker(): Ticker {
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
  };
}

function makeMinimalAnalysis(): AnalysisDetail {
  return {
    what_changed: "OPEC cut output.",
    mechanism_summary: "Supply reduction raises oil prices.",
    beneficiaries: ["Oil majors"],
    losers: ["Airlines"],
    beneficiary_tickers: ["XOM"],
    loser_tickers: ["AAL"],
    assets_to_watch: ["CL=F"],
    confidence: "medium",
  };
}

function makeMinimalFreshness(): FreshnessBlock {
  return {
    bucket: "warm",
    natural_bucket: "warm",
    event_age_days: 3,
    is_frozen: false,
    force_bypassed: false,
  };
}

function makeMinimalMarket(): MarketResult {
  return {
    note: "Market note.",
    details: {},
    tickers: [makeMinimalTicker()],
  };
}

function makeMinimalResponse(): AnalyzeResponse {
  return {
    headline: "OPEC cuts output",
    stage: "developing",
    persistence: "1w",
    analysis: makeMinimalAnalysis(),
    market: makeMinimalMarket(),
    freshness: makeMinimalFreshness(),
    is_mock: false,
    event_date: "2026-04-10",
  };
}

// ---------------------------------------------------------------------------
// 1. Confidence is a closed union, not an open string
// ---------------------------------------------------------------------------

describe("Confidence type", () => {
  it("accepts the three valid values", () => {
    const values: Confidence[] = ["low", "medium", "high"];
    expect(values).toHaveLength(3);
  });

  it("is used on AnalysisDetail.confidence", () => {
    const a = makeMinimalAnalysis();
    // This assignment proves the type accepts Confidence values
    const c: Confidence = a.confidence;
    expect(["low", "medium", "high"]).toContain(c);
  });
});

// ---------------------------------------------------------------------------
// 2. FreshnessBlock fields are all required
// ---------------------------------------------------------------------------

describe("FreshnessBlock", () => {
  it("has all 5 fields as required (no undefined)", () => {
    const f = makeMinimalFreshness();
    expect(f.bucket).toBeDefined();
    expect(f.natural_bucket).toBeDefined();
    expect(typeof f.event_age_days).toBe("number");
    expect(typeof f.is_frozen).toBe("boolean");
    expect(typeof f.force_bypassed).toBe("boolean");
  });

  it("bucket values match backend enum", () => {
    const valid: FreshnessBucket[] = ["hot", "warm", "stable", "frozen", "legacy"];
    expect(valid).toHaveLength(5);
    // "cooling" is NOT a valid bucket
    expect(valid).not.toContain("cooling");
  });
});

// ---------------------------------------------------------------------------
// 3. Ticker.spark is required (not optional)
// ---------------------------------------------------------------------------

describe("Ticker shape", () => {
  it("spark is always an array", () => {
    const t = makeMinimalTicker();
    expect(Array.isArray(t.spark)).toBe(true);
  });

  it("nullable fields accept null", () => {
    const t: Ticker = {
      ...makeMinimalTicker(),
      direction_tag: null,
      return_1d: null,
      return_5d: null,
      return_20d: null,
      volume_ratio: null,
      vs_xle_5d: null,
    };
    expect(t.direction_tag).toBeNull();
    expect(t.return_1d).toBeNull();
  });

  it("stale/last_trade_date are optional", () => {
    const t = makeMinimalTicker();
    expect(t.stale).toBeUndefined();
    expect(t.last_trade_date).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 4. MoverTicker.decay and decay_evidence are required
// ---------------------------------------------------------------------------

describe("MoverTicker shape", () => {
  it("decay and decay_evidence are always present", () => {
    const mt: MoverTicker = {
      symbol: "XOM",
      role: "beneficiary",
      return_5d: 3.0,
      direction: "supports ↑",
      spark: [100, 101],
      decay: "Accelerating",
      decay_evidence: "5d +3.0% intensifying vs 20d +2.0%",
    };
    expect(typeof mt.decay).toBe("string");
    expect(typeof mt.decay_evidence).toBe("string");
  });
});

// ---------------------------------------------------------------------------
// 5. MarketMover does NOT include overlay fields
// ---------------------------------------------------------------------------

describe("MarketMover shape", () => {
  it("does not include policy/macro overlay fields", () => {
    const m: MarketMover = {
      event_id: 1,
      headline: "Test",
      mechanism_summary: "",
      event_date: "2026-04-10",
      stage: "developing",
      persistence: "1w",
      impact: 3.5,
      support_ratio: 0.8,
      tickers: [],
    };
    // These fields should NOT exist on MarketMover
    const obj = m as Record<string, unknown>;
    expect(obj["currency_channel"]).toBeUndefined();
    expect(obj["policy_sensitivity"]).toBeUndefined();
    expect(obj["inventory_context"]).toBeUndefined();
    expect(obj["real_yield_context"]).toBeUndefined();
    expect(obj["policy_constraint"]).toBeUndefined();
  });

  it("does include transmission_chain and if_persists as optional", () => {
    const m: MarketMover = {
      event_id: 1,
      headline: "Test",
      mechanism_summary: "",
      event_date: "2026-04-10",
      stage: "developing",
      persistence: "1w",
      impact: 3.5,
      support_ratio: 0.8,
      tickers: [],
      transmission_chain: ["a", "b"],
      if_persists: { horizon: "6m" },
    };
    expect(m.transmission_chain).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// 6. MarketContext.rates and regime_vector are required
// ---------------------------------------------------------------------------

describe("MarketContext shape", () => {
  it("rates and regime_vector are always present", () => {
    const ctx: MarketContext = {
      built_at: "2026-04-12T12:00:00Z",
      source: "yfinance",
      snapshots: [],
      snapshots_meta: { total: 0, fresh: 0, stale: 0, unavailable: 0 },
      stress: {
        regime: "Unknown",
        signals: {
          vix_elevated: false,
          term_inversion: false,
          credit_widening: false,
          safe_haven_bid: false,
          breadth_deterioration: false,
        },
        raw: {},
        available: false,
      },
      rates: {
        regime: "Unknown",
        nominal: { label: "US10Y" },
        real_proxy: { label: "TIP" },
        breakeven_proxy: { label: "BE10Y" },
        raw: {},
        available: false,
      },
      regime_vector: {
        inflation: "unknown",
        policy_stance: "unknown",
        fx: "unknown",
        growth_stress: "unknown",
        available: false,
      },
      highlights: [],
      highlights_meta: { count: 0, source: "movers/today" },
    };
    // Both are required — no optional chaining needed
    expect(ctx.rates.regime).toBeDefined();
    expect(ctx.regime_vector.available).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 7. AnalysisDetail has degraded and validation_warnings
// ---------------------------------------------------------------------------

describe("AnalysisDetail optional backend fields", () => {
  it("accepts degraded flag", () => {
    const a: AnalysisDetail = {
      ...makeMinimalAnalysis(),
      degraded: true,
    };
    expect(a.degraded).toBe(true);
  });

  it("accepts validation_warnings array", () => {
    const a: AnalysisDetail = {
      ...makeMinimalAnalysis(),
      validation_warnings: ["ticker XOM has stale data"],
    };
    expect(a.validation_warnings).toHaveLength(1);
  });

  it("omits both when not present (typical case)", () => {
    const a = makeMinimalAnalysis();
    expect(a.degraded).toBeUndefined();
    expect(a.validation_warnings).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 8. AnalyzeResponse round-trip
// ---------------------------------------------------------------------------

describe("AnalyzeResponse", () => {
  it("full payload satisfies type without casting", () => {
    const r = makeMinimalResponse();
    expect(r.headline).toBe("OPEC cuts output");
    expect(r.analysis.confidence).toBe("medium");
    expect(r.market.tickers[0].spark).toEqual([100, 101, 102]);
    expect(r.freshness?.is_frozen).toBe(false);
    expect(r.freshness?.event_age_days).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// 9. _buildNewsPath — pagination URL contract
// ---------------------------------------------------------------------------

describe("_buildNewsPath", () => {
  it("first page has no cursor — emits limit only", () => {
    expect(_buildNewsPath(30)).toBe("/news?limit=30");
  });

  it("next page attaches the server-issued cursor verbatim", () => {
    expect(_buildNewsPath(30, "eyJzYyI6NX0")).toBe("/news?limit=30&cursor=eyJzYyI6NX0");
  });

  it("no arguments returns bare /news", () => {
    expect(_buildNewsPath()).toBe("/news");
  });

  it("cursor only (no limit) omits limit param", () => {
    expect(_buildNewsPath(undefined, "cur-xyz")).toBe("/news?cursor=cur-xyz");
  });

  it("empty-string cursor is treated as no cursor", () => {
    expect(_buildNewsPath(30, "")).toBe("/news?limit=30");
  });

  it("URL-encodes cursors containing special chars", () => {
    // The cursor we emit is base64url, but URLSearchParams must still escape
    // any stray characters that slipped through — verify contract holds.
    expect(_buildNewsPath(30, "a/b+c=")).toBe("/news?limit=30&cursor=a%2Fb%2Bc%3D");
  });
});

// ---------------------------------------------------------------------------
// 10. /portfolio response shapes — bare list vs filtered envelope
// ---------------------------------------------------------------------------

function makeMinimalPortfolioEntry(overrides: Partial<PortfolioEntry> = {}): PortfolioEntry {
  return {
    id: 1,
    headline: "OPEC cuts output",
    event_date: "2026-04-10",
    timestamp: null,
    stage: "developing",
    persistence: "1w",
    mechanism_summary: "Supply reduction.",
    beneficiaries: ["Oil majors"],
    losers: [],
    market_tickers: [],
    confidence: "medium",
    rating: null,
    revisit_snapshots: [],
    validation_outcome: "validated",
    support_ratio: 0.8,
    ...overrides,
  };
}

function makeMinimalEnvelope(items: PortfolioEntry[]): PortfolioFilteredResponse {
  return {
    items,
    thesis_state_counts:     { confirming: 1, partial: 0 },
    proof_quality_counts:    { proof_backed: 1 },
    queue_counts:            { confirming_now: 4, watch_falsifiers: 7, refresh_needed: 11, low_info_cleanup: 6 },
    mover_window_counts:     { today: 3, weekly: 7, persistent: 2, market: 5 },
    quality_tier_counts:     { actionable: 12, watch_only: 4, low_information: 1 },
    tradable_counts:         { true: 9, false: 4 },
    mechanism_subtype_counts: { tariff_cycle: 3 },
  };
}

describe("/portfolio bare-list response shape", () => {
  it("the default route returns PortfolioEntry[] — backward compatible", () => {
    const bare: PortfolioEntry[] = [makeMinimalPortfolioEntry()];
    expect(Array.isArray(bare)).toBe(true);
    expect(isPortfolioEnvelope(bare)).toBe(false);
  });

  it("unwrapPortfolioItems is identity on a bare list", () => {
    const bare: PortfolioEntry[] = [
      makeMinimalPortfolioEntry({ id: 1 }),
      makeMinimalPortfolioEntry({ id: 2 }),
    ];
    const items = unwrapPortfolioItems(bare);
    expect(items).toBe(bare);
    expect(items).toHaveLength(2);
  });

  it("unwrapPortfolioItems returns [] on null/undefined", () => {
    expect(unwrapPortfolioItems(null)).toEqual([]);
    expect(unwrapPortfolioItems(undefined)).toEqual([]);
  });
});

describe("/portfolio filtered envelope shape", () => {
  it("envelope satisfies PortfolioFilteredResponse without casting", () => {
    const env = makeMinimalEnvelope([makeMinimalPortfolioEntry()]);
    expect(env.items).toHaveLength(1);
    // Every count map the backend emits must be present on the type.
    expect(env.thesis_state_counts).toBeDefined();
    expect(env.proof_quality_counts).toBeDefined();
    expect(env.queue_counts).toBeDefined();
    expect(env.mover_window_counts).toBeDefined();
    expect(env.quality_tier_counts).toBeDefined();
    expect(env.tradable_counts).toBeDefined();
    expect(env.mechanism_subtype_counts).toBeDefined();
  });

  it("isPortfolioEnvelope discriminates bare list from envelope", () => {
    const bare: PortfolioEntry[] = [];
    const env = makeMinimalEnvelope([makeMinimalPortfolioEntry()]);
    expect(isPortfolioEnvelope(bare)).toBe(false);
    expect(isPortfolioEnvelope(env)).toBe(true);
    expect(isPortfolioEnvelope(null)).toBe(false);
    expect(isPortfolioEnvelope(undefined)).toBe(false);
  });

  it("unwrapPortfolioItems returns envelope.items unchanged", () => {
    const entries = [makeMinimalPortfolioEntry({ id: 7 })];
    const env = makeMinimalEnvelope(entries);
    const items = unwrapPortfolioItems(env);
    expect(items).toBe(entries);
    expect(items[0].id).toBe(7);
  });

  it("envelope tradable_counts has both string keys", () => {
    const env = makeMinimalEnvelope([]);
    // Wire contract: string keys "true"/"false" — JSON-friendly.
    expect(typeof env.tradable_counts.true).toBe("number");
    expect(typeof env.tradable_counts.false).toBe("number");
  });

  it("queue_counts and mover_window_counts are pre-filter (open dicts)", () => {
    // The backend returns counts for every known id in the closed enum;
    // contract here is "Record<string, number>" so the UI can size facets
    // without enumerating every key client-side.
    const env = makeMinimalEnvelope([]);
    expect(Object.keys(env.queue_counts).length).toBeGreaterThan(0);
    expect(Object.keys(env.mover_window_counts).length).toBeGreaterThan(0);
  });
});

describe("hasActivePortfolioFilters", () => {
  it("empty / null / undefined → false", () => {
    expect(hasActivePortfolioFilters(undefined)).toBe(false);
    expect(hasActivePortfolioFilters(null)).toBe(false);
    expect(hasActivePortfolioFilters({})).toBe(false);
  });

  it("any single set field → true", () => {
    expect(hasActivePortfolioFilters({ quality_tier: "actionable" })).toBe(true);
    expect(hasActivePortfolioFilters({ tradable: true })).toBe(true);
    expect(hasActivePortfolioFilters({ tradable: false })).toBe(true);
    expect(hasActivePortfolioFilters({ mechanism_subtype: "tariff_cycle" })).toBe(true);
    expect(hasActivePortfolioFilters({ queue: "confirming_now" })).toBe(true);
    expect(hasActivePortfolioFilters({ mover_window: "today" })).toBe(true);
    expect(hasActivePortfolioFilters({ thesis_state: "confirming" })).toBe(true);
    expect(hasActivePortfolioFilters({ proof_quality: "proof_backed" })).toBe(true);
    expect(hasActivePortfolioFilters({ low_information: false })).toBe(true);
  });

  it("empty mechanism_subtype string is treated as no filter", () => {
    // Routes through the open-keyed Record — empty string would hit the
    // backend as "match nothing", which is not the user's intent.
    expect(hasActivePortfolioFilters({ mechanism_subtype: "" })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 11. _buildPortfolioPath — query-param contract for filters
// ---------------------------------------------------------------------------

describe("_buildPortfolioPath", () => {
  it("default — no filters, default limit", () => {
    expect(_buildPortfolioPath()).toBe("/portfolio?limit=20");
  });

  it("custom limit, no filters", () => {
    expect(_buildPortfolioPath(50)).toBe("/portfolio?limit=50");
  });

  it("emits each of the 5 audit-listed filters as its own param", () => {
    const filters: PortfolioFilters = {
      quality_tier: "actionable",
      tradable: true,
      mechanism_subtype: "tariff_cycle",
      queue: "confirming_now",
      mover_window: "today",
    };
    const path = _buildPortfolioPath(20, filters);
    // Order is fixed by URLSearchParams insertion in the builder.
    expect(path).toBe(
      "/portfolio?limit=20"
      + "&queue=confirming_now"
      + "&mover_window=today"
      + "&quality_tier=actionable"
      + "&tradable=true"
      + "&mechanism_subtype=tariff_cycle",
    );
  });

  it("each filter individually round-trips", () => {
    expect(_buildPortfolioPath(20, { quality_tier: "watch_only" }))
      .toBe("/portfolio?limit=20&quality_tier=watch_only");
    expect(_buildPortfolioPath(20, { tradable: false }))
      .toBe("/portfolio?limit=20&tradable=false");
    expect(_buildPortfolioPath(20, { mechanism_subtype: "supply_squeeze" }))
      .toBe("/portfolio?limit=20&mechanism_subtype=supply_squeeze");
    expect(_buildPortfolioPath(20, { queue: "watch_falsifiers" }))
      .toBe("/portfolio?limit=20&queue=watch_falsifiers");
    expect(_buildPortfolioPath(20, { mover_window: "persistent" }))
      .toBe("/portfolio?limit=20&mover_window=persistent");
  });

  it("low_information=false is preserved as an explicit filter", () => {
    // Boolean filters need to differentiate "exclude low-info" (false)
    // from "no filter" (omitted).  The path must carry the literal.
    expect(_buildPortfolioPath(20, { low_information: false }))
      .toBe("/portfolio?limit=20&low_information=false");
    expect(_buildPortfolioPath(20, { low_information: true }))
      .toBe("/portfolio?limit=20&low_information=true");
  });

  it("URL-encodes filter values containing special characters", () => {
    // Mechanism subtypes are open-ended (per-family registry) so the
    // builder must encode anything URLSearchParams would normally
    // mangle — apostrophes, slashes, etc.
    expect(_buildPortfolioPath(20, { mechanism_subtype: "tariff & retaliation" }))
      .toBe("/portfolio?limit=20&mechanism_subtype=tariff+%26+retaliation");
  });

  it("combined thesis_state + proof_quality round-trip", () => {
    expect(
      _buildPortfolioPath(20, {
        thesis_state: "confirming",
        proof_quality: "proof_backed",
      }),
    ).toBe("/portfolio?limit=20&thesis_state=confirming&proof_quality=proof_backed");
  });
});
