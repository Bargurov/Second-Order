/**
 * Q2 — the Share page ticker row must use research wording (Beneficiary /
 * Exposed), never directional long / short framing. The /share/:id route is
 * publicly linkable, so the copy rule applies here too.
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { TickerRow, roleLabel } from "../share-page";
import type { Ticker } from "@/lib/api";

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
