/**
 * R5A — EventDossier shared research-note render smoke.
 *
 * The dossier consolidates substance that already exists on the frontend
 * (event metadata, mechanism, affected assets + realized move, the optional
 * event-study readout, the optional horizon falsifier, the scored outcome and
 * the standing claim boundary) into one coherent research note — it adds NO
 * new analytics and no new claims.
 *
 * Two render paths are pinned:
 *   - a FULL fixture (event + event-study + horizons) renders all ten
 *     professional-reader items;
 *   - a MINIMAL fixture (event only) renders the always-available items and
 *     OMITS the optional sections — honest degradation, never a fake stub.
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

function _eventStudy(): EventStudyBlock {
  return {
    status: "event_study_available",
    primary_ticker: "XLE",
    benchmark: "SPY",
    estimation_window_used: 120,
    per_horizon: [
      { horizon: 1, abnormal_return: 0.009, sar: 1.2, car: 0.009 },
      { horizon: 5, abnormal_return: 0.021, sar: 1.6, car: 0.028 },
      { horizon: 20, abnormal_return: 0.034, sar: 1.1, car: 0.041 },
    ],
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

const fullHtml = renderToStaticMarkup(
  <EventDossier event={_event()} eventStudy={_eventStudy()} horizons={_horizons()} />,
);
const fullVisible = fullHtml.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

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
    expect(fullVisible).toMatch(/\+3\.1%/); // XLE 5d 0.031
    expect(fullVisible).toMatch(/-1\.1%/);  // USO 5d -0.011
  });
  it("7 · event-study AR / SAR / CAR with an n=1 caveat", () => {
    expect(fullVisible.toLowerCase()).toContain("event-study");
    expect(fullVisible).toMatch(/\bAR\b/);
    expect(fullVisible).toMatch(/\bCAR\b/);
    expect(fullVisible.toLowerCase()).toContain("n=1");
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
// Minimal payload — honest degradation
// ---------------------------------------------------------------------------

describe("EventDossier — missing optional fields degrade honestly (R5A)", () => {
  const minimal = _event({ validation_status_v2: undefined });
  const html = renderToStaticMarkup(<EventDossier event={minimal} />);
  const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

  it("still renders the always-available items", () => {
    expect(visible).toContain("Sanctions tighten on seaborne crude exports");
    expect(visible).toContain("refiners with alternate sourcing benefit");
    expect(visible).toContain("XLE");
  });
  it("omits the event-study section when no event-study is supplied (no fake stub)", () => {
    expect(visible).not.toMatch(/\bAR\b/);
    expect(visible).not.toMatch(/\bCAR\b/);
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
// -290.0% move on a publicly shareable note.  (Event-study AR / CAR are
// fractional BHAR values and keep their own ×100 formatter — pinned above.)
// ---------------------------------------------------------------------------

describe("EventDossier — affected-asset returns are percent units (R5B)", () => {
  const ev = _event({
    market_tickers: [
      _ticker({ symbol: "ZZZ", role: "beneficiary", return_1d: 1.4, return_5d: -2.9, return_20d: 7.3 }),
    ],
  });
  const html = renderToStaticMarkup(<EventDossier event={ev} />);
  const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

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
// Copy honesty
// ---------------------------------------------------------------------------

describe("EventDossier — no banned framing (R5A)", () => {
  it("carries no buy / sell / trade / signal / overclaim framing", () => {
    const lc = fullVisible.toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed", "validated",
    ]) {
      expect(lc, `banned word "${w}" in the dossier`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});
