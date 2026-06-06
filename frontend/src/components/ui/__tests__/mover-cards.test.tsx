/**
 * Render + logic pins for the consolidated Event-Activity empty state.
 *
 * Pattern mirrors ``tracked-evidence-card.test.tsx``: vitest with
 * ``react-dom/server.renderToStaticMarkup`` (no jsdom, no setup file).
 *
 * Pinned behaviours:
 *  - ``allMoverWindowsEmpty`` is true only when today, weekly, and
 *    persistent are all empty; any populated window flips it false (so the
 *    page keeps the per-window cards when at least one window has items).
 *  - ``EventActivityEmpty`` renders the P2 title / explanation / 24h / 5d /
 *    persistent rows / footer verbatim, as one coherent block.
 *  - The block carries none of the forbidden surface-words (buy / sell /
 *    alpha / proven / validated / signal / proof).
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { MarketMover } from "@/lib/api";
import { EventActivityEmpty, allMoverWindowsEmpty } from "../mover-cards";

const none: MarketMover[] = [];
const one = [{} as MarketMover];

describe("allMoverWindowsEmpty", () => {
  it("is true only when today, weekly, and persistent are all empty", () => {
    expect(allMoverWindowsEmpty(none, none, none)).toBe(true);
  });

  it("is false when any single window has at least one item", () => {
    expect(allMoverWindowsEmpty(one, none, none)).toBe(false);
    expect(allMoverWindowsEmpty(none, one, none)).toBe(false);
    expect(allMoverWindowsEmpty(none, none, one)).toBe(false);
  });
});

describe("EventActivityEmpty", () => {
  const html = renderToStaticMarkup(<EventActivityEmpty />);

  it("renders the consolidated title and explanation", () => {
    expect(html).toContain("No events currently qualify for these windows");
    expect(html).toContain(
      "Event activity surfaces analyzed events once their forward price windows print",
    );
    expect(html).toContain("not a data error");
  });

  it("renders the 24h, 5-day, and persistent rows verbatim", () => {
    expect(html).toContain("24h — no event-linked moves in the last trading day.");
    expect(html).toContain(
      "5-day — no events with a settled five-day window in range.",
    );
    expect(html).toContain(
      "Persistent — no event meets the high-impact, still-moving bar (strict by design; never backfilled).",
    );
  });

  it("renders the footer note", () => {
    expect(html).toContain(
      "Movers reappear here automatically as newly analyzed events price into each window.",
    );
  });

  it("uses no buy / sell / validated-as-success language", () => {
    const lc = html.toLowerCase();
    for (const word of ["buy", "sell", "alpha", "proven", "validated", "signal", "proof"]) {
      expect(lc).not.toContain(word);
    }
  });
});
