/**
 * R5C — EventDossier integration into the Archive / Event Detail surface.
 *
 * `EventDetailDossierView` is the pure, read-only research-note section of the
 * archive event-detail view: the shared EventDossier leads, the raw "Market
 * Check" table follows as supporting tape (sparkline + volume the dossier's
 * compact line lacks), then assets-to-watch.  `EventDetail` keeps the
 * event-study `useQuery` and the interactive Rating / Notes / Cascade.
 *
 * Archive rows carry `validation_status_v2` (routes/events.py decorates every
 * row), so — unlike the Share `/export/json` payload — the dossier's scored
 * outcome renders here.  Archive carries NO typed horizon / falsifier payload,
 * so `horizons` is never passed and the falsifier section stays absent.
 *
 * Pure / presentational (no React Query, no jsdom), matching the project's
 * existing render-smoke pattern (renderToStaticMarkup).
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { SavedEvent, Ticker, EventStudyBlock } from "@/lib/api";
import { VALIDATION_V2_NOT_CLAIMED } from "@/lib/claim-copy";
import { EventDetailDossierView } from "../recent-events";

// ---------------------------------------------------------------------------
// Fixtures — market_tickers returns are PERCENT units (market_check.py * 100).
// ---------------------------------------------------------------------------

function _ticker(over: Partial<Ticker> = {}): Ticker {
  return {
    symbol: "XLE",
    role: "beneficiary",
    label: "supporting",
    direction_tag: "supporting",
    return_1d: 1.2,
    return_5d: 3.1,
    return_20d: 9.7,
    volume_ratio: 1.3,
    vs_xle_5d: null,
    spark: [1, 2, 3],
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
      _ticker({ symbol: "USO", role: "loser", label: "contradicting", direction_tag: "contradicting", return_1d: -0.4, return_5d: -1.1, return_20d: 0.2 }),
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

const strip = (html: string) => html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

describe("recent-events EventDetailDossierView — EventDossier integration (R5C)", () => {
  const full = renderToStaticMarkup(
    <EventDetailDossierView event={_event()} eventStudy={_eventStudy()} />,
  );
  const fullVisible = strip(full);

  it("renders the EventDossier research note from existing archive data", () => {
    expect(fullVisible).toContain("Sanctions tighten on seaborne crude exports"); // headline
    expect(fullVisible).toContain("refiners with alternate sourcing benefit");     // mechanism
    expect(fullVisible).toContain("XLE");                                          // affected asset
    expect(fullVisible).toMatch(/\+3\.1%/);                                        // realized 5d move (percent)
  });

  it("keeps the standing claim-boundary / not-claimed line visible", () => {
    expect(full).toContain(VALIDATION_V2_NOT_CLAIMED);
  });

  it("surfaces the scored outcome from validation_status_v2 with the honest label", () => {
    // Archive rows carry validation_status_v2 (Share's /export/json does not),
    // so the scored outcome renders here — as the honest "Any-supporting" label.
    expect(fullVisible).toContain("Any-supporting");
    expect(fullVisible).toContain("Three of four directional names aligned.");
  });

  it("renders the event-study readout when eventStudy data is supplied", () => {
    expect(fullVisible.toLowerCase()).toContain("event-study");
    expect(fullVisible).toMatch(/\bAR\b/);
    expect(fullVisible).toMatch(/\bCAR\b/);
  });

  it("omits the event-study readout when no eventStudy is supplied (no fake AR / SAR / CAR)", () => {
    const bare = strip(renderToStaticMarkup(<EventDetailDossierView event={_event()} />));
    expect(bare).not.toMatch(/\bAR\b/);
    expect(bare).not.toMatch(/\bCAR\b/);
  });

  it("renders no falsifier text — archive carries no typed horizon / falsifier payload", () => {
    expect(fullVisible).not.toContain("Thesis fails if");
  });

  it("keeps the raw Market Check table below as supporting tape", () => {
    expect(fullVisible).toContain("Market Check");
    expect(fullVisible).toContain("1.3x"); // MarketTable's volume-ratio column — unique to the table
  });

  it("carries no banned buy / sell / trade / signal / overclaim framing across the whole view", () => {
    const lc = fullVisible.toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed", "validated",
    ]) {
      expect(lc, `banned word "${w}" in the archive detail dossier view`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});
