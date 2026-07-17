/**
 * Render contract for the shared ``ReactionProfileCard`` (P2).
 *
 * SSR render-smoke via ``react-dom/server.renderToStaticMarkup`` (no
 * jsdom), mirroring ``event-study-card.test.tsx``.  The card is the
 * single mounted Reaction Profile consumer (fresh Analyze and the
 * Archive-detail cached restore both land here), so these tests are the
 * consumer-regression suite for every surface that shows the block.
 *
 * Pinned P2 behaviours: longest-scorable active horizon; visible,
 * non-selectable unavailable horizons; explicit fallback wording;
 * raw-price-path basis labeling; visible basis and horizon
 * disagreement; first-class endpoint-peak right-censoring; bounded
 * null/unavailable states; and the claim-language guard.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { ReactionProfileTicker, ReactionProfileV1Block } from "@/lib/api";
import {
  MIXED_HORIZONS_LABEL,
  NO_CLASSIFICATION_AT_1D,
  RAW_PATH_BASIS_NOTE,
  RAW_PATH_CLASSIFICATION_LABEL,
  RIGHT_CENSORED_LABEL,
  RIGHT_CENSORED_NOTE,
} from "@/lib/reaction-profile-consumer";
import { ReactionProfileCard } from "../reaction-profile-card";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function fullTicker(): ReactionProfileTicker {
  return {
    symbol: "NOC",
    reaction_profile_basis: "forward_anchored",
    return_1d: 1.1,
    return_5d: 2.4,
    return_20d: 3.9,
    return_60d: null,
    benchmark_relative_return_1d: 0.6,
    benchmark_relative_return_5d: -0.8,
    benchmark_relative_return_20d: 1.2,
    peak_move_5d: 4.0,
    time_to_peak_5d: 3,
    fade_or_hold_label_5d: "fade",
    peak_move_20d: 5.2,
    time_to_peak_20d: 12,
    fade_or_hold_label_20d: "hold",
    peak_move_60d: null,
    time_to_peak_60d: null,
    fade_or_hold_label_60d: "insufficient",
  };
}

function ticker20dInsufficient(): ReactionProfileTicker {
  return {
    ...fullTicker(),
    return_20d: null,
    peak_move_20d: null,
    time_to_peak_20d: null,
    fade_or_hold_label_20d: "insufficient",
  };
}

function tickerOnly1d(): ReactionProfileTicker {
  return {
    symbol: "VLO",
    reaction_profile_basis: "same_day_fallback",
    return_1d: -0.9,
    benchmark_relative_return_1d: -0.4,
    return_5d: null,
    return_20d: null,
    return_60d: null,
    peak_move_5d: null,
    time_to_peak_5d: null,
    fade_or_hold_label_5d: "insufficient",
    peak_move_20d: null,
    time_to_peak_20d: null,
    fade_or_hold_label_20d: "insufficient",
    peak_move_60d: null,
    time_to_peak_60d: null,
    fade_or_hold_label_60d: "insufficient",
  };
}

function tickerUnscorable(): ReactionProfileTicker {
  return {
    symbol: "JETS",
    reaction_profile_basis: "unscorable",
    return_1d: null,
    return_5d: null,
    return_20d: null,
    return_60d: null,
    peak_move_5d: null,
    time_to_peak_5d: null,
    fade_or_hold_label_5d: "insufficient",
    peak_move_20d: null,
    time_to_peak_20d: null,
    fade_or_hold_label_20d: "insufficient",
    peak_move_60d: null,
    time_to_peak_60d: null,
    fade_or_hold_label_60d: "insufficient",
  };
}

function tickerEndpointPeak20d(): ReactionProfileTicker {
  return {
    ...fullTicker(),
    return_20d: 6.0,
    peak_move_20d: 6.0,
    time_to_peak_20d: 20,
    fade_or_hold_label_20d: "hold",
  };
}

function blockWith(tickers: ReactionProfileTicker[], overrides?: Partial<ReactionProfileV1Block>): ReactionProfileV1Block {
  return {
    available: tickers.some((t) =>
      [t.return_1d, t.return_5d, t.return_20d, t.return_60d].some((v) => v != null),
    ),
    reason: "hydrated per-ticker profile(s) from cached close windows",
    tickers,
    n_tickers: tickers.length,
    ...overrides,
  };
}

function render(block: ReactionProfileV1Block, initialHorizon?: "1d" | "5d" | "20d"): string {
  return renderToStaticMarkup(
    <ReactionProfileCard block={block} initialHorizon={initialHorizon} />,
  );
}

// ---------------------------------------------------------------------------
// Active horizon and availability
// ---------------------------------------------------------------------------

describe("ReactionProfileCard — active horizon", () => {
  it("defaults to the longest scorable horizon", () => {
    const html = render(blockWith([fullTicker()]));
    expect(html).toContain("Active horizon: 20d");
  });

  // (2)/(9) fallback is explicit, not a tooltip
  it("falls back to 5d with a visible explanation when 20d is not scorable", () => {
    const html = render(blockWith([ticker20dInsufficient()]));
    expect(html).toContain("Active horizon: 5d");
    expect(html).toContain(
      "Showing 5d — 20d has insufficient observations for this event.",
    );
  });

  // (10) a requested unavailable horizon cannot become active
  it("ignores an initial horizon that is not scorable", () => {
    const html = render(blockWith([ticker20dInsufficient()]), "20d");
    expect(html).toContain("Active horizon: 5d");
  });

  it("honors a scorable initial horizon", () => {
    const html = render(blockWith([fullTicker()]), "5d");
    expect(html).toContain("Active horizon: 5d");
  });

  // (3) only-1d events stay presentable without inventing a classification
  it("activates 1d when only the 1d return exists and states the structural limit", () => {
    const html = render(blockWith([tickerOnly1d()]));
    expect(html).toContain("Active horizon: 1d");
    expect(html).toContain("Showing 1d — 20d and 5d are unavailable for this event.");
    expect(html).toContain(NO_CLASSIFICATION_AT_1D);
    expect(html).not.toContain(">Hold<");
    expect(html).not.toContain(">Fade<");
  });

  // (7)/(8) all three frozen horizons stay visible; unavailable ones disabled
  it("renders all three horizon controls with explicit states and disables unscorable ones", () => {
    const html = render(blockWith([ticker20dInsufficient()]));
    for (const h of ["1d", "5d", "20d"]) expect(html).toContain(`>${h}<`);
    expect(html).toContain("disabled");
    expect(html).toContain("insufficient observations");
    const htmlFull = render(blockWith([fullTicker()]));
    expect(htmlFull).toContain("available");
  });
});

// ---------------------------------------------------------------------------
// Classification basis
// ---------------------------------------------------------------------------

describe("ReactionProfileCard — raw-price basis", () => {
  // (11)/(12)
  it("labels the classification as a raw-price path read, never bare", () => {
    const html = render(blockWith([fullTicker()]));
    expect(html).toContain(RAW_PATH_CLASSIFICATION_LABEL);
    expect(html).toContain(RAW_PATH_BASIS_NOTE);
    expect(html).toContain(">Hold<");
  });

  it("shows raw and benchmark-relative returns as separate, named values", () => {
    const html = render(blockWith([fullTicker()]));
    expect(html).toContain("+3.90%"); // raw 20d
    expect(html).toContain("+1.20%"); // benchmark-relative 20d
    expect(html.toLowerCase()).toContain("benchmark-relative");
  });

  // (13) basis disagreement is visible at the active horizon
  it("flags a basis-sensitive readout when raw and benchmark-relative signs disagree", () => {
    const html = render(blockWith([fullTicker()]), "5d");
    expect(html).toContain("Basis-sensitive readout");
    expect(html).toContain("+2.40%");
    expect(html).toContain("-0.80%");
  });

  // (14) agreement produces no score or confidence artifact
  it("does not turn basis agreement into a score", () => {
    const html = render(blockWith([fullTicker()]));
    expect(html).not.toContain("Basis-sensitive readout");
    expect(html.toLowerCase()).not.toContain("confidence");
    expect(html.toLowerCase()).not.toContain("consensus");
  });
});

// ---------------------------------------------------------------------------
// Horizon disagreement
// ---------------------------------------------------------------------------

describe("ReactionProfileCard — across horizons", () => {
  // (16) mixed labels surface as an explicit neutral state
  it("shows Mixed across horizons with each horizon listed", () => {
    const html = render(blockWith([fullTicker()]));
    expect(html).toContain(MIXED_HORIZONS_LABEL);
    expect(html).toContain(">Fade<");
    expect(html).toContain(">Hold<");
  });

  // (17) agreement stays individually visible and neutral
  it("lists agreeing horizons individually without a robustness claim", () => {
    const agree = {
      ...fullTicker(),
      return_5d: 3.2,
      peak_move_5d: 4.0,
      fade_or_hold_label_5d: "hold",
    };
    const html = render(blockWith([agree]));
    expect(html).not.toContain(MIXED_HORIZONS_LABEL);
    expect(html).toContain("Available horizons agree");
    expect(html.toLowerCase()).not.toContain("robust");
    expect(html.toLowerCase()).not.toContain("confirm");
  });

  // (18) unavailable horizons stay visible as states in the comparison
  it("keeps unavailable horizons visible in the comparison", () => {
    const html = render(blockWith([ticker20dInsufficient()]));
    expect(html).toContain("Across horizons");
    expect(html).toContain("insufficient observations");
  });
});

// ---------------------------------------------------------------------------
// Endpoint peak / right-censoring
// ---------------------------------------------------------------------------

describe("ReactionProfileCard — endpoint peak", () => {
  // (20)/(22) the qualifier is first-class and adjacent to the classification
  it("marks a final-session peak as right-censored next to the classification", () => {
    const html = render(blockWith([tickerEndpointPeak20d()]));
    expect(html).toContain(RIGHT_CENSORED_LABEL);
    expect(html).toContain(RIGHT_CENSORED_NOTE);
    // Engine label stays traceable, but never unqualified: the qualifier
    // must appear before the across-horizon section, adjacent to the row.
    const label = html.indexOf(">Hold<");
    const qualifier = html.indexOf(RIGHT_CENSORED_LABEL);
    const acrossSection = html.indexOf("Across horizons");
    expect(label).toBeGreaterThan(-1);
    expect(qualifier).toBeGreaterThan(-1);
    expect(acrossSection).toBeGreaterThan(-1);
    expect(qualifier).toBeLessThan(acrossSection);
  });

  // (21)
  it("does not qualify an interior peak", () => {
    const html = render(blockWith([fullTicker()]));
    expect(html).not.toContain(RIGHT_CENSORED_LABEL);
  });

  // (23) the endpoint ratio stays traceable without implying a full path
  it("keeps peak and final values visible alongside the qualifier", () => {
    const html = render(blockWith([tickerEndpointPeak20d()]));
    expect(html).toContain("+6.00%");
    expect(html).toContain(RIGHT_CENSORED_LABEL);
  });
});

// ---------------------------------------------------------------------------
// Null safety and bounded unavailable states
// ---------------------------------------------------------------------------

describe("ReactionProfileCard — null safety", () => {
  // (25) an entirely unavailable block renders a bounded state
  it("renders a bounded unavailable state when nothing is scorable", () => {
    const html = render(
      blockWith([tickerUnscorable()], {
        available: false,
        reason: "0/1 per-ticker profile(s) hydrated; per-ticker status: 1 cache_miss",
      }),
    );
    expect(html).toContain("Unscorable");
    expect(html).toContain("cache_miss");
    expect(html).not.toContain("Active horizon:");
    expect(html).not.toContain(">Hold<");
  });

  it("renders a bounded state when the block has no tickers", () => {
    const html = render(
      blockWith([], { available: false, reason: "no market_tickers on this event" }),
    );
    expect(html).toContain("no market_tickers on this event");
  });

  // (24) no NaN / undefined / blank leaks in any state
  it("never leaks NaN, undefined or empty labels", () => {
    const fixtures = [
      blockWith([fullTicker()]),
      blockWith([ticker20dInsufficient()]),
      blockWith([tickerOnly1d()]),
      blockWith([tickerEndpointPeak20d()]),
      blockWith([tickerUnscorable()], { available: false, reason: "0/1 hydrated" }),
    ];
    for (const block of fixtures) {
      const html = render(block);
      expect(html).not.toContain("NaN");
      expect(html).not.toContain("undefined");
      expect(html).not.toContain("[object Object]");
    }
  });

  it("discloses when more tickers exist than are rendered", () => {
    const many = [
      fullTicker(),
      { ...fullTicker(), symbol: "AAA" },
      { ...fullTicker(), symbol: "BBB" },
      { ...fullTicker(), symbol: "CCC" },
      { ...fullTicker(), symbol: "DDD" },
      { ...fullTicker(), symbol: "EEE" },
    ];
    const html = render(blockWith(many));
    expect(html).toContain("Showing first 4 of 6 tickers");
  });
});

// ---------------------------------------------------------------------------
// Claim-language guard over every rendered state
// ---------------------------------------------------------------------------

describe("ReactionProfileCard — claim language", () => {
  const FORBIDDEN = [
    "buy",
    "sell",
    "signal",
    "opportunity",
    "alpha",
    "predictive",
    "statistically significant",
    "caused",
    "validated strategy",
    "strong performance",
    "confirmed",
    "best horizon",
    "strongest horizon",
    "winning basis",
    "consensus classification",
    "confidence score",
  ];

  it("renders no affirmative claim language in any state", () => {
    const fixtures = [
      blockWith([fullTicker()]),
      blockWith([ticker20dInsufficient()]),
      blockWith([tickerOnly1d()]),
      blockWith([tickerEndpointPeak20d()]),
      blockWith([tickerUnscorable()], { available: false, reason: "0/1 hydrated" }),
    ];
    for (const block of fixtures) {
      const html = render(block).toLowerCase();
      for (const term of FORBIDDEN) {
        expect(html).not.toContain(term);
      }
    }
  });

  it("does not describe the longer horizon as better", () => {
    const html = render(blockWith([fullTicker()])).toLowerCase();
    expect(html).not.toContain("better");
    expect(html).not.toContain("stronger");
    expect(html).not.toContain("winning");
  });
});
