/**
 * Q2 — the Share page ticker row must use research wording (Beneficiary /
 * Exposed), never directional long / short framing. The /share/:id route is
 * publicly linkable, so the copy rule applies here too.
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { TickerRow, roleLabel, ShareDossierView } from "../share-page";
import type { Ticker, SavedEvent, EventStudyBlock } from "@/lib/api";
import { VALIDATION_V2_NOT_CLAIMED } from "@/lib/claim-copy";

function tk(role: string, sym: string): Ticker {
  return { symbol: sym, role, return_1d: 1, return_5d: 1, return_20d: 1 } as unknown as Ticker;
}

describe("share-page roleLabel", () => {
  it("maps to research wording, not long/short", () => {
    expect(roleLabel("beneficiary")).toBe("Beneficiary");
    expect(roleLabel("loser")).toBe("Exposed");
  });
});

describe("share-page TickerRow render", () => {
  const html = renderToStaticMarkup(
    <table>
      <tbody>
        <TickerRow ticker={tk("beneficiary", "AAA")} />
        <TickerRow ticker={tk("loser", "BBB")} />
      </tbody>
    </table>,
  );
  it("renders research roles, not long/short", () => {
    expect(html).toContain("Beneficiary");
    expect(html).toContain("Exposed");
    expect(html).not.toContain(">long<");
    expect(html).not.toContain(">short<");
  });
});

// ---------------------------------------------------------------------------
// R5B — EventDossier integration on the Share page
//
// ShareDossierView is the pure body of the Share page: the EventDossier
// research note leads, the F1-guarded "Market reaction (raw)" table follows
// as supporting tape, then assets-to-watch and the footer.  It is rendered
// with existing Share data only (SavedEvent + the optional, already-fetched
// event-study block) — no horizon / falsifier payload is available on /share,
// so the dossier's falsifier section must stay absent (never faked).
//
// Pure / presentational (no React Query, no jsdom), matching this file's
// existing pattern; ShareContent keeps the event-study useQuery and renders
// this view.
// ---------------------------------------------------------------------------

// market_tickers returns are PERCENT units (market_check.py * 100).
function _shareTicker(over: Partial<Ticker> = {}): Ticker {
  return {
    symbol: "XLE",
    role: "beneficiary",
    label: "supports",
    direction_tag: "supports",
    return_1d: 1.2,
    return_5d: 3.1,
    return_20d: 9.7,
    volume_ratio: null,
    vs_xle_5d: null,
    spark: [],
    ...over,
  } as unknown as Ticker;
}

function _shareEvent(over: Partial<SavedEvent> = {}): SavedEvent {
  return {
    id: 42,
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
      _shareTicker(),
      _shareTicker({ symbol: "USO", role: "loser", direction_tag: "contradicts", return_1d: -0.4, return_5d: -1.1, return_20d: 0.2 }),
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

function _shareEventStudy(): EventStudyBlock {
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

describe("share-page ShareDossierView — EventDossier integration (R5B)", () => {
  const full = renderToStaticMarkup(
    <ShareDossierView ev={_shareEvent()} eventStudy={_shareEventStudy()} />,
  );
  const fullVisible = strip(full);

  it("renders the EventDossier research note from existing Share data", () => {
    expect(fullVisible).toContain("Sanctions tighten on seaborne crude exports"); // headline
    expect(fullVisible).toContain("refiners with alternate sourcing benefit");     // mechanism
    expect(fullVisible).toContain("XLE");                                          // affected asset
    expect(fullVisible).toMatch(/\+3\.1%/);                                        // realized 5d move
  });

  it("keeps the standing claim-boundary / not-claimed line visible", () => {
    expect(full).toContain(VALIDATION_V2_NOT_CLAIMED);
  });

  it("surfaces the scored outcome with the honest label, not 'validated'-as-success", () => {
    expect(fullVisible).toContain("Any-supporting");
    expect(fullVisible).toContain("Three of four directional names aligned.");
  });

  it("renders the event-study readout when eventStudy data is supplied", () => {
    expect(fullVisible.toLowerCase()).toContain("event-study");
    expect(fullVisible).toMatch(/\bAR\b/);
    expect(fullVisible).toMatch(/\bCAR\b/);
  });

  it("omits the event-study readout when no eventStudy is supplied (no fake AR / SAR / CAR)", () => {
    const bare = strip(renderToStaticMarkup(<ShareDossierView ev={_shareEvent()} />));
    expect(bare).not.toMatch(/\bAR\b/);
    expect(bare).not.toMatch(/\bCAR\b/);
  });

  it("renders no falsifier text — Share carries no horizon / falsifier payload", () => {
    expect(fullVisible).not.toContain("Thesis fails if");
  });

  it("keeps the raw-return table and dossier consistent — the same figure reads identically on both surfaces", () => {
    // XLE 20d = 9.7% must appear in both the dossier line and the raw table.
    const hits = fullVisible.match(/\+9\.7%/g) ?? [];
    expect(hits.length).toBeGreaterThanOrEqual(2);
  });

  it("carries no banned buy / sell / trade / signal / overclaim framing across the whole view", () => {
    const lc = fullVisible.toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed", "validated",
    ]) {
      expect(lc, `banned word "${w}" on the share view`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});
