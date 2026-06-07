/**
 * Q2 — Backtest scorecard:
 *  - ticker roles render as research wording (Beneficiary / Exposed), never as
 *    L/S trade legs;
 *  - no-data cells render a real em dash, not the literal "—" escape (the
 *    JSX-text escape bug from the Q1 audit).
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { EventScorecard, roleLabel } from "../backtest";
import type { SavedEvent, BacktestResult } from "@/lib/api";

function ev(): SavedEvent {
  return {
    id: 1,
    headline: "Test event",
    stage: "initial",
    persistence: "active",
    confidence: "high",
    event_date: "2026-01-01",
    market_tickers: [],
  } as unknown as SavedEvent;
}

function result(): BacktestResult {
  return {
    outcomes: [
      { symbol: "AAA", role: "beneficiary", direction: "supports ↑", return_5d: 1.2 },
      { symbol: "BBB", role: "loser", direction: null, return_5d: null },
    ],
    score: { supporting: 1, total: 2 },
  } as unknown as BacktestResult;
}

describe("backtest roleLabel", () => {
  it("maps to research wording, not long/short or a bare L/S", () => {
    expect(roleLabel("beneficiary")).toBe("Beneficiary");
    expect(roleLabel("loser")).toBe("Exposed");
    for (const r of ["beneficiary", "loser", ""]) {
      const out = roleLabel(r).toLowerCase();
      for (const banned of ["long", "short"]) expect(out).not.toContain(banned);
      expect(["l", "s"]).not.toContain(out);
    }
  });
});

describe("EventScorecard render", () => {
  const html = renderToStaticMarkup(
    <EventScorecard event={ev()} result={result()} loading={false} />,
  );
  it("shows research roles, not L/S trade legs", () => {
    expect(html).toContain("Beneficiary");
    expect(html).toContain("Exposed");
    expect(html).not.toContain(">L<");
    expect(html).not.toContain(">S<");
  });
  it("renders a real em dash in the no-data cell, not the literal escape", () => {
    expect(html).toContain("—"); // real em dash present
    expect(html).not.toContain("\\u2014"); // literal backslash-u escape absent
  });
});
