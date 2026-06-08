/**
 * R5A / T9A — EventDossier shared research-note render smoke.
 *
 * The dossier consolidates substance that already exists on the frontend
 * (event metadata, mechanism, affected assets + realized move, the optional
 * finance-native event-study readout, the optional horizon falsifier, the
 * scored outcome and the standing claim boundary) into one coherent research
 * note — it adds NO new analytics and no new claims.
 *
 * T9A upgrades the event-study section to a finance-native, horizon-by-horizon
 * readout: raw move, benchmark move, abnormal return, plus CAR / SAR when
 * present — using only fields already on the EventStudyBlock payload.  When the
 * payload reports insufficient_data, a compact unavailable note replaces the
 * metric rows (never blank metrics, never a fake stub).
 *
 * Presentational only — no React Query, no network.  vitest +
 * renderToStaticMarkup, no jsdom.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type {
  SavedEvent,
  Ticker,
  EventStudyBlock,
  HorizonCheckpoints,
} from "@/lib/api";
import { VALIDATION_V2_SCOPE_CAVEAT, VALIDATION_V2_NOT_CLAIMED } from "@/lib/claim-copy";
import { EventDossier } from "../event-dossier";

// The required, exact n=1 caveat for the finance-native readout.
const ES_CAVEAT =
  "Single-event readout — n = 1, descriptive only; not statistical significance or a permanent asset forecast.";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// market_tickers returns are PERCENT units (market_check.py * 100), e.g. 3.1
// means +3.1% — NOT fractions.  Fixtures mirror the real data contract.
function _ticker(over: Partial<Ticker> = {}): Ticker {
  return {
    symbol: "XLE",
    role: "beneficiary",
    label: "supports",
    direction_tag: "supports",
    return_1d: 1.2,
    return_5d: 3.1,
    return_20d: 5.8,
    volume_ratio: null,
    vs_xle_5d: null,
    spark: [],
    ...over,
  } as unknown as Ticker;
}

function _event(over: Partial<SavedEvent> = {}): SavedEvent {
  return {
    id: 7,
    timestamp: "2026-03-02T00:00:00Z",
    headline: "Sanctions tighten on seaborne crude exports",
    stage: "developing",
    persistence: "active",
    what_changed: "New export limits cut seaborne crude flows.",
    mechanism_summary:
      "Supply tightens; refiners with alternate sourcing benefit, import-reliant names exposed.",
    beneficiaries: ["Domestic refiners"],
    losers: ["Import-reliant utilities"],
    assets_to_watch: ["XLE", "USO"],
    confidence: "high",
    market_note: "",
    market_tickers: [
      _ticker(),
      _ticker({ symbol: "USO", role: "loser", direction_tag: "contradicts", return_1d: -0.4, return_5d: -1.1, return_20d: 0.2 }),
    ],
    event_date: "2026-03-02",
    notes: "",
    rating: null,
    validation_status_v2: {
      status: "validated",
      ratio: 0.75,
      reason: "Three of four directional names aligned.",
      counts: { total_tickers: 4, directional: 4, supporting: 3, contradicting: 1 },
    },
    ...over,
  } as unknown as SavedEvent;
}

// Available readout — every horizon carries raw / benchmark / abnormal / SAR /
// CAR.  Values chosen so each rendered percent is distinct from the ticker
// fixture's percents, so a presence assertion pins the event-study cell.
function _eventStudy(): EventStudyBlock {
  return {
    status: "event_study_available",
    primary_ticker: "XLE",
    benchmark: "SPY",
    estimation_window_used: 120,
    per_horizon: [
      { horizon: 1, raw_return: 0.021, benchmark_return: 0.006, abnormal_return: 0.015, sar: 0.65, car: 0.015 },
      { horizon: 5, raw_return: 0.044, benchmark_return: 0.019, abnormal_return: 0.025, sar: 1.6, car: 0.027 },
      { horizon: 20, raw_return: 0.083, benchmark_return: 0.026, abnormal_return: 0.057, sar: 1.1, car: 0.06 },
    ],
  };
}

// Unavailable readout — payload reports insufficient_data with blocking reasons
// (the #1 / thin-cache case).  No per_horizon rows.
function _eventStudyUnavailable(): EventStudyBlock {
  return {
    status: "insufficient_data",
    primary_ticker: "TSLA",
    benchmark: "SPY",
    blocking_reasons: ["no_cached_prices_for_primary_ticker", "missing_forward_cache_5d"],
  };
}

function _horizons(): HorizonCheckpoints {
  return {
    timing_profile: "delayed_pass_through",
    horizons: [
      { horizon: "1d", expected: ["XLE up on the print"], confirms_if: ["XLE outperforms SPY 1d"], falsifies_if: ["XLE closes below its event-day level"] },
      { horizon: "5d", expected: ["sector spread holds"], confirms_if: ["spread widens by 5d"], falsifies_if: ["spread fully retraces by 5d"] },
      { horizon: "20d", expected: ["move persists"], confirms_if: ["20d move exceeds the 5d move"], falsifies_if: ["20d move reverts to zero"] },
    ],
  };
}

const strip = (h: string) => h.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

const fullHtml = renderToStaticMarkup(
  <EventDossier event={_event()} eventStudy={_eventStudy()} horizons={_horizons()} />,
);
const fullVisible = strip(fullHtml);

// ---------------------------------------------------------------------------
// Full payload — all ten professional-reader items
// ---------------------------------------------------------------------------

describe("EventDossier — full payload renders the ten reader items (R5A)", () => {
  it("1 · headline", () => {
    expect(fullVisible).toContain("Sanctions tighten on seaborne crude exports");
  });
  it("2 · event date", () => {
    expect(fullVisible).toContain("2026-03-02");
  });
  it("3 · mechanism, stage and confidence", () => {
    expect(fullVisible).toContain("refiners with alternate sourcing benefit");
    expect(fullVisible.toLowerCase()).toContain("developing");
    expect(fullVisible.toLowerCase()).toContain("high");
  });
  it("4 · affected assets with research roles (not L/S)", () => {
    expect(fullVisible).toContain("XLE");
    expect(fullVisible).toContain("USO");
    expect(fullVisible).toContain("Beneficiary");
    expect(fullVisible).toContain("Exposed");
  });
  it("5 · expected transmission / what changed", () => {
    expect(fullVisible).toContain("New export limits cut seaborne crude flows.");
  });
  it("6 · realized 1d / 5d / 20d move", () => {
    expect(fullVisible).toMatch(/\+3\.1%/); // XLE 5d ticker percent
    expect(fullVisible).toMatch(/-1\.1%/);  // USO 5d ticker percent
  });
  it("7 · event-study readout with AR / CAR and the n=1 caveat", () => {
    expect(fullVisible.toLowerCase()).toContain("event-study");
    expect(fullVisible).toMatch(/\bAR\b/);
    expect(fullVisible).toMatch(/\bCAR\b/);
    expect(fullVisible).toContain(ES_CAVEAT);
  });
  it("8 · falsifier (thesis fails if) from existing falsifies_if text", () => {
    expect(fullVisible).toContain("Thesis fails if");
    expect(fullVisible).toContain("XLE closes below its event-day level");
  });
  it("9 · scored outcome / status (honest label, not 'validated'-as-success)", () => {
    expect(fullVisible).toContain("Any-supporting");
    expect(fullVisible).toContain("Three of four directional names aligned.");
  });
  it("10 · standing claim boundary (reused caveat + not-claimed constants)", () => {
    expect(fullHtml).toContain(VALIDATION_V2_SCOPE_CAVEAT);
    expect(fullHtml).toContain(VALIDATION_V2_NOT_CLAIMED);
  });
});

// ---------------------------------------------------------------------------
// T9A — finance-native event-study readout
// ---------------------------------------------------------------------------

describe("EventDossier — finance-native event-study readout (T9A)", () => {
  it("names the primary ticker and benchmark", () => {
    expect(fullVisible).toContain("XLE");
    expect(fullVisible).toContain("SPY");
  });

  it("renders the 1d / 5d / 20d horizon labels", () => {
    expect(fullVisible).toContain("1d");
    expect(fullVisible).toContain("5d");
    expect(fullVisible).toContain("20d");
  });

  it("renders horizon rows in ascending order (via the distinct raw moves)", () => {
    // raw_return 0.021 / 0.044 / 0.083 → +2.1% / +4.4% / +8.3% are unique to
    // the event-study rows, so their order pins the row order.
    const i1 = fullVisible.indexOf("+2.1%");
    const i5 = fullVisible.indexOf("+4.4%");
    const i20 = fullVisible.indexOf("+8.3%");
    expect(i1).toBeGreaterThan(-1);
    expect(i1).toBeLessThan(i5);
    expect(i5).toBeLessThan(i20);
  });

  it("renders the raw move per horizon", () => {
    expect(fullVisible).toContain("+2.1%"); // 1d raw
    expect(fullVisible).toContain("+8.3%"); // 20d raw
  });

  it("renders the benchmark move per horizon", () => {
    expect(fullVisible).toContain("+0.6%"); // 1d benchmark
    expect(fullVisible).toContain("+1.9%"); // 5d benchmark
  });

  it("renders the abnormal return per horizon", () => {
    expect(fullVisible).toContain("+1.5%"); // 1d AR
    expect(fullVisible).toContain("+5.7%"); // 20d AR
  });

  it("renders CAR and SAR when present", () => {
    expect(fullVisible).toContain("+6.0%"); // 20d CAR
    expect(fullVisible).toContain("1.60");  // 5d SAR (point estimate, not percent)
  });

  it("carries the exact n=1 descriptive caveat", () => {
    expect(fullVisible).toContain(ES_CAVEAT);
  });
});

describe("EventDossier — event-study unavailable degrades honestly (T9A)", () => {
  const visible = strip(
    renderToStaticMarkup(<EventDossier event={_event()} eventStudy={_eventStudyUnavailable()} />),
  );

  it("renders a compact unavailable note", () => {
    expect(visible.toLowerCase()).toContain("event-study readout unavailable");
  });

  it("does not render the metric readout (no legend / no n=1 readout caveat)", () => {
    expect(visible).not.toContain("AR = raw");
    expect(visible).not.toContain(ES_CAVEAT);
  });

  it("still shows the separate raw affected-asset tape (missingness is scoped to the event-study)", () => {
    expect(visible).toContain("XLE");
  });
});

// ---------------------------------------------------------------------------
// Minimal payload — honest degradation
// ---------------------------------------------------------------------------

describe("EventDossier — missing optional fields degrade honestly (R5A)", () => {
  const minimal = _event({ validation_status_v2: undefined });
  const html = renderToStaticMarkup(<EventDossier event={minimal} />);
  const visible = strip(html);

  it("still renders the always-available items", () => {
    expect(visible).toContain("Sanctions tighten on seaborne crude exports");
    expect(visible).toContain("refiners with alternate sourcing benefit");
    expect(visible).toContain("XLE");
  });
  it("omits the event-study section entirely when no event-study is supplied (no fake stub)", () => {
    expect(visible).not.toMatch(/\bAR\b/);
    expect(visible).not.toMatch(/\bCAR\b/);
    expect(visible).not.toContain(ES_CAVEAT);
    expect(visible.toLowerCase()).not.toContain("event-study readout unavailable");
  });
  it("omits the falsifier section when no horizons are supplied (no fake stub)", () => {
    expect(visible).not.toContain("Thesis fails if");
  });
  it("omits the scored-outcome section when validation_status_v2 is absent", () => {
    expect(visible).not.toContain("Any-supporting");
  });
  it("keeps the standing claim boundary even on the minimal payload", () => {
    expect(html).toContain(VALIDATION_V2_NOT_CLAIMED);
  });
});

// ---------------------------------------------------------------------------
// Affected-asset return units (R5B)
//
// market_tickers returns arrive as PERCENT (market_check.py computes
// (end - start) / start * 100), e.g. -2.9 means -2.9%.  The dossier must
// render them at face value — never re-scaled by 100, which would print a
// -290.0% move on a publicly shareable note.  (Event-study fields are
// fractional and keep their own ×100 formatter — pinned above.)
// ---------------------------------------------------------------------------

describe("EventDossier — affected-asset returns are percent units (R5B)", () => {
  const ev = _event({
    market_tickers: [
      _ticker({ symbol: "ZZZ", role: "beneficiary", return_1d: 1.4, return_5d: -2.9, return_20d: 7.3 }),
    ],
  });
  const visible = strip(renderToStaticMarkup(<EventDossier event={ev} />));

  it("renders percent returns at face value", () => {
    expect(visible).toContain("-2.9%");
    expect(visible).toContain("+7.3%");
  });
  it("does not multiply percent returns by 100", () => {
    expect(visible).not.toContain("-290.0%");
    expect(visible).not.toContain("+730.0%");
  });
});

// ---------------------------------------------------------------------------
// Transmission chain — ordered prose steps (T6B-A)
// ---------------------------------------------------------------------------

describe("EventDossier — transmission chain (T6B-A)", () => {
  const steps = [
    "Export limits cut seaborne crude flows.",
    "Physical supply tightens; benchmark crude firms.",
    "Refiners with alternate sourcing gain; import-reliant names carry the cost.",
  ];
  const withVisible = strip(
    renderToStaticMarkup(<EventDossier event={_event({ transmission_chain: steps } as Partial<SavedEvent>)} />),
  );

  it("renders a Transmission block with the prose steps in order", () => {
    expect(withVisible).toContain("Transmission");
    for (const s of steps) expect(withVisible).toContain(s);
    expect(withVisible.indexOf(steps[0]!)).toBeLessThan(withVisible.indexOf(steps[1]!));
    expect(withVisible.indexOf(steps[1]!)).toBeLessThan(withVisible.indexOf(steps[2]!));
  });

  it("renders the prose / not-a-taxonomy caveat", () => {
    expect(withVisible).toContain(
      "Descriptive transmission narrative — prose, n = 1, not a structured taxonomy or falsifier.",
    );
  });

  it("omits the block entirely when transmission_chain is absent", () => {
    const v = strip(renderToStaticMarkup(<EventDossier event={_event()} />));
    expect(v).not.toContain("Descriptive transmission narrative");
  });

  it("omits the block when transmission_chain is empty or blank-only", () => {
    const v = strip(
      renderToStaticMarkup(<EventDossier event={_event({ transmission_chain: ["", "   "] } as Partial<SavedEvent>)} />),
    );
    expect(v).not.toContain("Descriptive transmission narrative");
  });

  it("carries no banned framing in the transmission block", () => {
    const lc = withVisible.toLowerCase();
    for (const w of ["buy", "sell", "long", "short", "alpha", "signal", "trade", "live trading", "proof", "proves", "confirmed"]) {
      expect(lc, `banned word "${w}"`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});

// ---------------------------------------------------------------------------
// Copy honesty
// ---------------------------------------------------------------------------

describe("EventDossier — no banned framing (R5A / T9A)", () => {
  it("carries no buy / sell / trade / signal / overclaim framing on the full readout", () => {
    const lc = fullVisible.toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed", "validated",
    ]) {
      expect(lc, `banned word "${w}" in the dossier`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });

  it("carries no banned framing on the unavailable readout", () => {
    const lc = strip(
      renderToStaticMarkup(<EventDossier event={_event()} eventStudy={_eventStudyUnavailable()} />),
    ).toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed", "validated",
    ]) {
      expect(lc, `banned word "${w}" in the unavailable dossier`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});
