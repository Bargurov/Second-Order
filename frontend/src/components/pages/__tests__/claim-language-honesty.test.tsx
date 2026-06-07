/**
 * F1 — claim-language honesty guard.
 *
 * Locks the reframe so a later copy sweep (F2) cannot silently regress:
 *
 *  1. The raw event-window return section is titled "Market reaction (raw)",
 *     NOT "Market Validation" — raw 1d/5d/20d returns must not pose as
 *     event-study inference.  (Asserted on the rendered SharePage; the
 *     AnalysisView tape kicker shares the same copy constant.)
 *
 *  2. The scored validation_status_v2 verdict carries a bounding scope
 *     caveat marking it as tape-direction agreement, not benchmark-adjusted
 *     inference — while its status label and ratio stay unchanged (additive
 *     only; no scoring / taxonomy change).
 *
 * Presentational render-smoke, matching the project's existing pattern
 * (renderToStaticMarkup, no jsdom).  ShareContent needs a QueryClient
 * because it fetches the (here unresolved) event-study block.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { SavedEvent, Ticker, ValidationStatusV2Block } from "@/lib/api";
import {
  MARKET_REACTION_LABEL,
  MARKET_REACTION_SUBLABEL,
  VALIDATION_V2_SCOPE_CAVEAT,
  VALIDATION_V2_NOT_CLAIMED,
} from "@/lib/claim-copy";
import { ShareContent } from "../share-page";
import { ValidationStatusCard } from "../analysis-view";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function _ticker(over: Partial<Ticker> = {}): Ticker {
  return {
    symbol: "XLE",
    role: "beneficiary",
    return_1d: 0.01,
    return_5d: -0.02,
    return_20d: 0.03,
    direction_tag: "supports",
    label: "supports",
    ...over,
  } as unknown as Ticker;
}

function _event(): SavedEvent {
  return {
    id: 3,
    timestamp: "2026-04-04T00:00:00Z",
    headline: "Test event",
    stage: "realized",
    persistence: "high",
    what_changed: "x",
    mechanism_summary: "y",
    beneficiaries: ["A"],
    losers: ["B"],
    assets_to_watch: ["XLE"],
    confidence: "high",
    market_note: "",
    market_tickers: [
      _ticker(),
      _ticker({ symbol: "USO", role: "loser", direction_tag: "contradicts" }),
    ],
    event_date: "2026-04-04",
    notes: "",
    rating: null,
  } as unknown as SavedEvent;
}

function _v2(): ValidationStatusV2Block {
  return {
    status: "validated",
    ratio: 0.8,
    reason: "3 of 4 directional names aligned.",
    counts: { total_tickers: 4, directional: 4, supporting: 3, contradicting: 1 },
    event_age_days: 59,
  } as unknown as ValidationStatusV2Block;
}

function renderShare(ev: SavedEvent): string {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <ShareContent ev={ev} />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Copy invariants — the constants themselves must not overclaim
// ---------------------------------------------------------------------------

describe("F1 — claim copy is honest", () => {
  it("labels raw returns as a raw market reaction, not 'Market Validation'", () => {
    expect(MARKET_REACTION_LABEL).toBe("Market reaction (raw)");
    expect(MARKET_REACTION_LABEL.toLowerCase()).not.toContain("validation");
  });
  it("sublabel marks returns raw / not benchmark-adjusted", () => {
    expect(MARKET_REACTION_SUBLABEL).toContain("not benchmark-adjusted");
  });
  it("v2 caveat bounds the verdict as non-inferential without overclaiming", () => {
    expect(VALIDATION_V2_SCOPE_CAVEAT).toContain("not benchmark-adjusted event-study inference");
    // Word-boundary match (Q1 L8): catches a standalone overclaim word but
    // does not false-match an innocent superset ("alpha" in "alphanumeric",
    // "significant" in "insignificant", etc.).
    const lc = VALIDATION_V2_SCOPE_CAVEAT.toLowerCase();
    for (const w of ["proof", "proven", "confirmed", "significant", "alpha"]) {
      expect(lc, `overclaim word "${w}" leaked into the caveat`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});

// ---------------------------------------------------------------------------
// SharePage raw section
// ---------------------------------------------------------------------------

describe("F1 — SharePage raw-return section is honestly labelled", () => {
  const html = renderShare(_event());

  it("titles the section 'Market reaction (raw)'", () => {
    expect(html).toContain(MARKET_REACTION_LABEL);
  });
  it("does not pose raw returns as 'Market Validation'", () => {
    expect(html).not.toContain("Market Validation");
  });
  it("renders the raw / not-benchmark-adjusted sublabel", () => {
    expect(html).toContain("not benchmark-adjusted");
  });
});

// ---------------------------------------------------------------------------
// validation_status_v2 verdict — bounded, not changed
// ---------------------------------------------------------------------------

describe("F1 — validation_status_v2 verdict is bounded, not changed", () => {
  const html = renderToStaticMarkup(<ValidationStatusCard block={_v2()} />);

  it("adds the scope caveat marking it as tape-direction agreement", () => {
    expect(html).toContain(VALIDATION_V2_SCOPE_CAVEAT);
  });
  it("leaves the scored status label and ratio unchanged", () => {
    expect(html).toContain("Validated");
    expect(html).toContain("80%");
  });

  // R2A — claim-boundary honesty placement.  The caveat and an explicit
  // "Not claimed" line must sit in the verdict area (above the counts grid),
  // not be buried in a lower footer.  ``"Directional"`` is the first counts-row
  // label, so it marks the start of the mid-card block.
  it("places the scope caveat in the verdict area, above the counts grid (not only a footer)", () => {
    const caveatAt = html.indexOf(VALIDATION_V2_SCOPE_CAVEAT);
    const countsAt = html.indexOf("Directional");
    expect(caveatAt).toBeGreaterThan(-1);
    expect(countsAt).toBeGreaterThan(-1);
    expect(caveatAt).toBeLessThan(countsAt);
  });
  it("renders an explicit 'Not claimed' line in the verdict area", () => {
    expect(html).toContain(VALIDATION_V2_NOT_CLAIMED);
    expect(html.indexOf(VALIDATION_V2_NOT_CLAIMED)).toBeLessThan(html.indexOf("Directional"));
  });
  it("the not-claimed copy carries no banned framing", () => {
    const lc = VALIDATION_V2_NOT_CLAIMED.toLowerCase();
    for (const w of ["buy", "sell", "long", "short", "alpha", "signal", "proof", "proves", "confirmed", "prediction", "live trading"]) {
      expect(lc, `banned word "${w}" in the not-claimed copy`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});
