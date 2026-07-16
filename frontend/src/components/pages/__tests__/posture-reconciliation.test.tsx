/**
 * L1 — investor-facing posture reconciliation guard.
 *
 * Locks the Phase L1 product-posture decisions so a later copy or styling
 * sweep cannot silently regress them:
 *
 *  1. Portfolio no longer presents archive results as "strongest analyses
 *     ranked" — the ordering subtitle states its descriptive basis and its
 *     non-claim.
 *  2. The research-tab lead metric is a "Validated share" with a visible
 *     resolved denominator and a claim-boundary footnote — never a
 *     "Hit rate" / "Win Rate" framed as payoff, and never coloured by a
 *     beat-the-coinflip threshold.
 *  3. The engine's trade-actionability flag (``actionability_check.tradable``)
 *     never reaches the professional UI as a label, chip, or filter control —
 *     while the underlying API fields and filter helpers stay intact.
 *  4. The Simulator (hand-picked hindsight portfolio Return / Win Rate) is
 *     removed from the page module.
 *  5. Backtest's aggregate reads "Directional agreement" with its
 *     denominator footnote, and the per-event score badge carries no
 *     success/failure colour verdict.
 *  6. Analyze's confidence-calibration note is a descriptive archive share
 *     under the any-support rule — not "validated historically".
 *
 * Presentational render-smoke, matching the project's existing pattern
 * (renderToStaticMarkup, no jsdom).
 */

import { describe, expect, it } from "vitest";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type {
  BacktestResult,
  PortfolioEntry,
  SavedEvent,
  TrackRecordBreakdown,
} from "@/lib/api";
import * as portfolioPage from "../portfolio-page";
import {
  EngineFilterBar,
  ENGINE_FILTERS_DEFAULT,
  PORTFOLIO_ORDER_SUBTITLE,
  PortfolioCard,
  ResearchHeadlineStrip,
} from "../portfolio-page";
import { AggregateSummary, EventScorecard } from "../backtest";
import {
  CALIBRATION_ARCHIVE_NOTE_TITLE,
  calibrationArchiveNote,
} from "../analysis-view";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function breakdown(): TrackRecordBreakdown {
  return {
    total_events: 12,
    validated_total: 4,
    contradicted_total: 3,
    revisit_scored: 5,
    hit_rate: 0.571,
    by_mechanism_family: [],
    by_regime: [],
    by_compound_regime: [],
    generated_at: "2026-07-16T00:00:00Z",
  } as unknown as TrackRecordBreakdown;
}

function entry(): PortfolioEntry {
  return {
    id: 7,
    headline: "Test portfolio entry",
    event_date: "2026-04-01",
    timestamp: "2026-04-01T00:00:00",
    stage: "realized",
    persistence: "high",
    mechanism_summary: "mechanism",
    beneficiaries: ["AAA"],
    losers: ["BBB"],
    market_tickers: [],
    confidence: "high",
    rating: null,
    revisit_snapshots: [],
    validation_outcome: "validated",
    support_ratio: 0.75,
    quality_tier: "actionable",
    quality_warnings: [],
    actionability_check: { tradable: true },
    mechanism_subtype: "supply_shock",
    thesis_state_reason: null,
  } as unknown as PortfolioEntry;
}

function backtestEvent(): SavedEvent {
  return {
    id: 1,
    headline: "Backtest event",
    stage: "initial",
    persistence: "active",
    confidence: "high",
    event_date: "2026-01-01",
    market_tickers: [],
  } as unknown as SavedEvent;
}

function lowRatioResult(): BacktestResult {
  return {
    outcomes: [
      { symbol: "AAA", role: "beneficiary", direction: "contradicts ↓", return_5d: -1.2 },
    ],
    score: { supporting: 0, total: 3 },
  } as unknown as BacktestResult;
}

function withQuery(node: ReactElement): string {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>{node}</QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// 1 · Portfolio header — descriptive ordering, not an opportunity ranking
// ---------------------------------------------------------------------------

describe("L1 — portfolio ordering subtitle", () => {
  it("states the descriptive basis and the non-claim", () => {
    expect(PORTFOLIO_ORDER_SUBTITLE).toContain("descriptive order");
    expect(PORTFOLIO_ORDER_SUBTITLE).toContain("not an opportunity ranking");
  });

  it("carries no opportunity-ranking framing", () => {
    const lc = PORTFOLIO_ORDER_SUBTITLE.toLowerCase();
    for (const w of ["strongest", "ranked", "best", "win", "tradable", "actionable"]) {
      expect(lc, `banned word "${w}" in the subtitle`).not.toMatch(
        new RegExp(`\\b${w}\\b`),
      );
    }
  });
});

// ---------------------------------------------------------------------------
// 2 · Research-tab lead metric — validated share with denominator + boundary
// ---------------------------------------------------------------------------

describe("L1 — ResearchHeadlineStrip", () => {
  const html = renderToStaticMarkup(<ResearchHeadlineStrip data={breakdown()} />);

  it("labels the lead metric as a validated share with its resolved denominator", () => {
    expect(html).toContain("Validated share");
    expect(html).toContain("7 resolved");
    expect(html).toContain("57%");
  });

  it("keeps validated / contradicted counts visible", () => {
    expect(html).toContain("Validated");
    expect(html).toContain("Contradicted");
  });

  it("renders the claim-boundary footnote", () => {
    expect(html).toContain("descriptive accounting");
    expect(html).toContain("not accuracy");
  });

  it("does not frame the share as a hit/win payoff metric", () => {
    for (const phrase of ["Hit rate", "Win Rate", "hit rate", "win rate", "did the discipline pay"]) {
      expect(html, `banned framing "${phrase}" returned`).not.toContain(phrase);
    }
  });

  it("does not colour the share by a success/failure threshold", () => {
    // The neutralized strip must not tone the percentage with the
    // supporting-teal / contradicting-coral pair keyed off 0.55 / 0.45.
    // Categorical count colours remain for the Validated / Contradicted
    // secondary metrics, so assert on the hero span specifically.
    const hero = html.slice(0, html.indexOf("Validated share"));
    expect(hero).not.toContain("#ee7d77");
  });
});

// ---------------------------------------------------------------------------
// 3 · Engine trade-actionability flag stays out of the professional UI
// ---------------------------------------------------------------------------

describe("L1 — tradable/actionable labels are absent", () => {
  it("PortfolioCard renders no tradable chip even when the flag is set", () => {
    const html = withQuery(<PortfolioCard entry={entry()} onOpen={() => {}} />);
    expect(/\btradable\b/i.test(html)).toBe(false);
    expect(html).not.toContain("Actionability");
    // The engine tier still surfaces under its viewer label.
    expect(html).toContain("high-quality");
  });

  it("EngineFilterBar offers no tradable filter control", () => {
    const html = renderToStaticMarkup(
      <EngineFilterBar
        filters={ENGINE_FILTERS_DEFAULT}
        onChange={() => {}}
        subtypeOptions={["supply shock"]}
        totalCount={4}
        filteredCount={4}
      />,
    );
    expect(/\btradable\b/i.test(html)).toBe(false);
    expect(html).not.toContain("Filter by tradable");
    // The remaining facets survive.
    expect(html).toContain("Tier · all");
    expect(html).toContain("Subtype · all");
  });

  it("the raw engine token 'actionable' stays out of viewer copy", () => {
    const cardHtml = withQuery(<PortfolioCard entry={entry()} onOpen={() => {}} />);
    // Attribute values may carry enum tokens; assert on visible text by
    // stripping tags first.
    const visible = cardHtml.replace(/<[^>]*>/g, " ");
    expect(/\bactionable\b/i.test(visible)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 4 · Simulator removal is pinned at the module boundary
// ---------------------------------------------------------------------------

describe("L1 — simulator surface is gone", () => {
  it("exports no simulator helpers from the portfolio page", () => {
    const moduleKeys = Object.keys(portfolioPage);
    expect(moduleKeys).not.toContain("groupPositionsByEvent");
    expect(moduleKeys).not.toContain("formatReturn");
    expect(moduleKeys).not.toContain("SimulatorTab");
    expect(moduleKeys).not.toContain("SnapshotStrip");
  });
});

// ---------------------------------------------------------------------------
// 5 · Backtest — directional agreement, no colour verdict
// ---------------------------------------------------------------------------

describe("L1 — backtest posture", () => {
  it("aggregate kicker reads 'Directional agreement', not a score overview", () => {
    const results = new Map<number, BacktestResult>([[1, lowRatioResult()]]);
    const html = renderToStaticMarkup(<AggregateSummary results={results} />);
    expect(html).toContain("Directional agreement");
    expect(html).not.toContain("Score overview");
  });

  it("a low agreement ratio renders no failure-coloured badge", () => {
    const html = renderToStaticMarkup(
      <EventScorecard
        event={backtestEvent()}
        result={lowRatioResult()}
        loading={false}
      />,
    );
    expect(html).toContain("0/3");
    expect(html).not.toContain("destructive");
  });
});

// ---------------------------------------------------------------------------
// 6 · Analyze — calibration note is an archive share, not validation
// ---------------------------------------------------------------------------

describe("L1 — confidence-calibration archive note", () => {
  const note = calibrationArchiveNote("high", { hit_rate: 0.62, n: 14 });

  it("names the rule and the denominator", () => {
    expect(note).toContain("of 14 archived high-confidence analyses");
    expect(note).toContain("any-support rule");
    expect(note).toContain("≥1 supporting ticker");
  });

  it("does not claim historical or predictive validation", () => {
    expect(/validated historically/i.test(note)).toBe(false);
    expect(/\bvalidated\b/i.test(note)).toBe(false);
  });

  it("the hover title states the claim boundary", () => {
    expect(CALIBRATION_ARCHIVE_NOTE_TITLE).toContain("not predictive");
    expect(CALIBRATION_ARCHIVE_NOTE_TITLE).toContain("Descriptive archive share");
  });
});
