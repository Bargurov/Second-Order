/**
 * P2-2 — state-machine contract for a streamed analysis
 * (``analysisStreamReducer`` + ``rowSettlementFor`` in
 * ``src/lib/analysis-stream.ts``, the production source of truth consumed by
 * ``AnalysisView``).
 *
 * The only path to ``phase === "complete"`` is a STRUCTURALLY VALID success
 * ``complete`` event; a truncated, invalid, or handled-failure terminal lands
 * in ``idle`` with the partial dropped (or kept only as identity chips for a
 * handled failure), so completed-only UI and export can never render.
 * ``rowSettlementFor`` fixes which Inbox callback each terminal outcome fires.
 */
import { describe, it, expect } from "vitest";
import type { AnalyzeResponse } from "../api";
import {
  analysisStreamReducer,
  INITIAL_ANALYSIS_STREAM_STATE,
  rowSettlementFor,
  type AnalysisStreamState,
} from "../analysis-stream";

function reduce(
  actions: Parameters<typeof analysisStreamReducer>[1][],
  start: AnalysisStreamState = INITIAL_ANALYSIS_STREAM_STATE,
): AnalysisStreamState {
  return actions.reduce(analysisStreamReducer, start);
}

const VALID_ANALYSIS = {
  what_changed: "x", mechanism_summary: "m",
  beneficiaries: ["A"], losers: ["B"],
  beneficiary_tickers: ["AAPL"], loser_tickers: ["MSFT"],
  assets_to_watch: ["AAPL"], confidence: "medium",
};
const MARKET = { note: "", details: {}, tickers: [] };
const CLASSIFY = { type: "event", stage: "classify", data: { stage: "initial", persistence: "short" } } as const;
const ANALYSIS = { type: "event", stage: "analysis", data: { analysis: VALID_ANALYSIS, is_mock: false } } as const;
const COMPLETE_OK = {
  type: "event", stage: "complete",
  data: {
    _phase: "complete", headline: "h", stage: "initial", persistence: "short",
    analysis: VALID_ANALYSIS, market: MARKET, is_mock: false, event_date: "2026-01-01",
  } as Record<string, unknown>,
} as const;

describe("analysisStreamReducer — completeness contract", () => {
  it("submit resets to classify with just the headline", () => {
    const s = reduce([{ type: "submit", headline: "Fed holds" }]);
    expect(s.phase).toBe("classify");
    expect(s.result?.headline).toBe("Fed holds");
    expect(s.error).toBeNull();
  });

  it("a full stream ending in a valid success complete reaches complete", () => {
    const s = reduce([{ type: "submit", headline: "h" }, CLASSIFY, ANALYSIS, COMPLETE_OK]);
    expect(s.phase).toBe("complete");
    expect(s.error).toBeNull();
    expect((s.result as AnalyzeResponse).analysis).toBeTruthy();
  });

  it("truncation (incomplete) after partials is NOT complete and DROPS the partial", () => {
    const s = reduce([
      { type: "submit", headline: "h" }, CLASSIFY, ANALYSIS,
      { type: "incomplete", message: "Analysis stream ended before completion." },
    ]);
    expect(s.phase).toBe("idle");
    expect(s.result).toBeNull();
    expect(s.error).toBe("Analysis stream ended before completion.");
  });

  it("a mock/failed complete is a handled failure, never complete", () => {
    const s = reduce([
      { type: "submit", headline: "h" }, CLASSIFY,
      {
        type: "event", stage: "complete",
        data: {
          _phase: "complete", headline: "h", stage: "", persistence: "", analysis: {},
          market: MARKET, is_mock: true, analysis_failed: true, failure_reason: "overloaded",
          event_date: "2026-01-01",
        },
      },
    ]);
    expect(s.phase).toBe("idle");
    expect(s.error).toBe("overloaded");
    expect((s.result as AnalyzeResponse | null)?.analysis).toBeUndefined();
  });

  it("REJECTS an arbitrary phase-only complete — cannot create a completed UI", () => {
    const s = reduce([
      { type: "submit", headline: "h" }, CLASSIFY, ANALYSIS,
      { type: "event", stage: "complete", data: { _phase: "complete" } },
    ]);
    expect(s.phase).not.toBe("complete");
    expect(s.phase).toBe("idle");
    expect(s.result).toBeNull();
    expect(s.error).toBeTruthy();
  });

  it("REJECTS a complete with malformed analysis — cannot create a completed UI", () => {
    const s = reduce([
      { type: "submit", headline: "h" }, CLASSIFY, ANALYSIS,
      { type: "event", stage: "complete", data: { ...COMPLETE_OK.data, analysis: [] } },
    ]);
    expect(s.phase).not.toBe("complete");
    expect(s.result).toBeNull();
  });

  it("incomplete clears even a fully-streamed partial analysis body", () => {
    const withPartial = reduce([{ type: "submit", headline: "h" }, CLASSIFY, ANALYSIS]);
    expect(withPartial.result?.analysis).toBeTruthy();
    const s = analysisStreamReducer(withPartial, { type: "incomplete", message: "gone" });
    expect(s.result).toBeNull();
    expect(s.phase).toBe("idle");
  });

  it("marketRefreshed replaces the market block on a completed result", () => {
    const done = reduce([{ type: "submit", headline: "h" }, CLASSIFY, ANALYSIS, COMPLETE_OK]);
    const refreshed = analysisStreamReducer(done, { type: "marketRefreshed", market: { foo: 1 } as never });
    expect((refreshed.result as AnalyzeResponse).market).toEqual({ foo: 1 });
    expect(refreshed.phase).toBe("complete");
  });

  it("marketRefreshed is a no-op when there is no result", () => {
    const s = analysisStreamReducer(INITIAL_ANALYSIS_STREAM_STATE, { type: "marketRefreshed", market: {} as never });
    expect(s.result).toBeNull();
  });
});

describe("rowSettlementFor — Inbox settlement mapping", () => {
  it("success settles as succeeded", () => expect(rowSettlementFor("success")).toBe("succeeded"));
  it("handled failure settles as failed", () => expect(rowSettlementFor("handled_failure")).toBe("failed"));
  it("incomplete/truncation settles as failed", () => expect(rowSettlementFor("incomplete")).toBe("failed"));
  it("cancellation settles as none", () => expect(rowSettlementFor("cancelled")).toBe("none"));
});
