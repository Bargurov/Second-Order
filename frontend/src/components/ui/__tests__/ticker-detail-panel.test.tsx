/**
 * Q2 — the ticker role badge must use research wording (Beneficiary / Exposed),
 * never directional trade-position framing (long / short). Second Order is a
 * research artifact, not a buy/sell tool.
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TickerDetailPanel, roleLabel } from "../ticker-detail-panel";
import type { TickerBase } from "@/lib/api";

describe("ticker roleLabel", () => {
  it("maps roles to research wording, not long/short", () => {
    expect(roleLabel("beneficiary")).toBe("Beneficiary");
    expect(roleLabel("loser")).toBe("Exposed");
    expect(roleLabel("exposed")).toBe("Exposed");
    expect(roleLabel(undefined)).toBe("Exposed");
  });
  it("never returns a trade-position word", () => {
    for (const r of ["beneficiary", "loser", "winner", "", null, undefined]) {
      const out = roleLabel(r).toLowerCase();
      for (const banned of ["long", "short", "buy", "sell"]) {
        expect(out).not.toContain(banned);
      }
    }
  });
});

describe("TickerDetailPanel role badge render", () => {
  function render(role: string): string {
    const ticker = { symbol: "AAA", role, return_5d: 1.1, return_20d: 2.2 } as unknown as TickerBase;
    return renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <TickerDetailPanel ticker={ticker} />
      </QueryClientProvider>,
    );
  }
  it("renders the research role, not long/short", () => {
    const benef = render("beneficiary");
    expect(benef).toContain("Beneficiary");
    expect(benef).not.toContain(">long<");

    const exposed = render("loser");
    expect(exposed).toContain("Exposed");
    expect(exposed).not.toContain(">short<");
  });
});
