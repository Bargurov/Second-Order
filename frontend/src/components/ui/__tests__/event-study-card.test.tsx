/**
 * Render smoke for the shared ``EventStudyCard``.
 *
 * The card is presentational only — no React Query, no network — so each
 * test renders it directly with a hand-built ``EventStudyBlock`` and
 * asserts the resulting HTML.  Pattern mirrors
 * ``components/ui/__tests__/tracked-evidence-card.test.tsx``: vitest with
 * ``react-dom/server.renderToStaticMarkup``, no jsdom, no setup file.
 *
 * Pinned behaviours:
 *
 *  - Ready state (``event_study_available``): the title, the "n = 1 ·
 *    point estimates only" subtitle, the AR / SAR / CAR columns, the
 *    1d / 5d / 20d horizon rows with signed values, the benchmark /
 *    estimation-window line, and the cautionary footnote all render.
 *  - Insufficient state: the "Not computable for this event." copy and
 *    the labelized blocking reasons render, and NO numeric table is
 *    emitted (the distinctive SAR value never appears).
 *  - Conservative vocabulary: neither state carries overclaim
 *    surface-words (proof / proven / confirmed / validated / significant
 *    / buy / sell / alpha).  The readout is descriptive, never a verdict.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { EventStudyBlock } from "@/lib/api";
import { EventStudyCard } from "../event-study-card";

// ---------------------------------------------------------------------------
// Fixtures — clean, distinctive values so format assertions stay robust.
// ---------------------------------------------------------------------------

function _readyBlock(): EventStudyBlock {
  return {
    status: "event_study_available",
    benchmark: "SPY",
    estimation_window_used: 60,
    per_horizon: [
      { horizon: 1, abnormal_return: 0.012, sar: 1.5, car: 0.012 },
      { horizon: 5, abnormal_return: -0.034, sar: -2.1, car: -0.03 },
      { horizon: 20, abnormal_return: -0.05, sar: -1.4, car: -0.045 },
    ],
  };
}

function _insufficientBlock(): EventStudyBlock {
  return {
    status: "insufficient_data",
    blocking_reasons: ["no_primary_ticker", "missing_forward_cache_5d"],
  };
}

const FORBIDDEN_WORDS = [
  "proof",
  "proven",
  "confirmed",
  "validated",
  "significant",
  "buy",
  "sell",
  "alpha",
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EventStudyCard — ready state", () => {
  const html = renderToStaticMarkup(<EventStudyCard block={_readyBlock()} />);

  it("renders the title and n=1 point-estimate subtitle", () => {
    expect(html).toContain("Event-study readout");
    expect(html).toContain("Single event · n = 1 · point estimates only");
  });

  it("renders AR / SAR / CAR columns and 1d / 5d / 20d rows", () => {
    expect(html).toContain(">AR<");
    expect(html).toContain(">SAR<");
    expect(html).toContain(">CAR<");
    expect(html).toContain(">1d<");
    expect(html).toContain(">5d<");
    expect(html).toContain(">20d<");
  });

  it("formats AR/CAR as signed percent and SAR as a signed number", () => {
    expect(html).toContain("+1.2%"); // abnormal_return 0.012
    expect(html).toContain("+1.50"); // sar 1.5
    expect(html).toContain("-2.10"); // sar -2.1
  });

  it("renders the benchmark / estimation-window line", () => {
    expect(html).toContain("vs SPY");
    expect(html).toContain("60-bar window");
  });

  it("renders the cautionary, non-verdict footnote", () => {
    expect(html).toContain("Not a pass/fail verdict");
    expect(html).not.toContain("Not computable for this event.");
  });
});

describe("EventStudyCard — insufficient state", () => {
  const html = renderToStaticMarkup(
    <EventStudyCard block={_insufficientBlock()} />,
  );

  it("renders the not-computable copy and labelized blocking reasons", () => {
    expect(html).toContain("Not computable for this event.");
    expect(html).toContain("No Primary Ticker");
    expect(html).toContain("Missing Forward Cache 5d");
  });

  it("emits no numeric table", () => {
    // The distinctive SAR value only exists inside the data table.
    expect(html).not.toContain("+1.50");
  });
});

describe("EventStudyCard — conservative vocabulary", () => {
  it("carries no overclaim surface-words in either state", () => {
    const ready = renderToStaticMarkup(
      <EventStudyCard block={_readyBlock()} />,
    ).toLowerCase();
    const insufficient = renderToStaticMarkup(
      <EventStudyCard block={_insufficientBlock()} />,
    ).toLowerCase();
    for (const word of FORBIDDEN_WORDS) {
      expect(ready).not.toContain(word);
      expect(insufficient).not.toContain(word);
    }
  });
});
