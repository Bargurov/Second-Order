/**
 * Pure consumer contract for the Reaction Profile readout (P2).
 *
 * These tests pin the deterministic helper layer that every Reaction
 * Profile consumer must route through: which horizon is active, which
 * horizons are selectable, how availability is described, how horizon
 * and basis disagreement are detected, and when an endpoint peak is
 * right-censored.  No React, no fetch, no browser globals.
 *
 * The helpers never re-classify a path: `hold / fade / reverse / flat /
 * insufficient` come verbatim from the frozen composer
 * (reaction_profile.py); the consumer layer only decides what may be
 * shown and how its limits are stated.
 *
 * Numbered comments reference the P2 fixture states (1-25).
 */

import { describe, expect, it } from "vitest";

import type { ReactionProfileTicker } from "@/lib/api";
import {
  ACTIVE_HORIZON_ORDER,
  BASIS_SENSITIVE_LABEL,
  FROZEN_DISPLAY_HORIZONS,
  HORIZON_FORWARD_BARS,
  MIXED_HORIZONS_LABEL,
  NO_CLASSIFICATION_AT_1D,
  RAW_PATH_BASIS_NOTE,
  RAW_PATH_CLASSIFICATION_LABEL,
  RIGHT_CENSORED_LABEL,
  RIGHT_CENSORED_NOTE,
  classifyTickerHorizon,
  describeHorizonFallback,
  detectBasisDisagreement,
  detectHorizonDisagreement,
  isEndpointPeakRightCensored,
  isHorizonSelectable,
  resolveActiveHorizon,
} from "@/lib/reaction-profile-consumer";

// ---------------------------------------------------------------------------
// Fixtures — hand-built per-ticker payloads mirroring reaction_profile_v1.
// Values are internally consistent with the frozen composer's decision
// table (e.g. a "hold" fixture really has |final|/|peak| >= 0.7).
// ---------------------------------------------------------------------------

/** Fully scorable at 5d and 20d; 5d fade vs 20d hold (mixed); 60d insufficient. */
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
    benchmark_relative_return_60d: null,
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

/** 20d insufficient (window not filled); 5d and 1d scorable. */
function ticker20dInsufficient(): ReactionProfileTicker {
  return {
    ...fullTicker(),
    return_20d: null,
    peak_move_20d: null,
    time_to_peak_20d: null,
    fade_or_hold_label_20d: "insufficient",
  };
}

/** Same-day fallback: only the 1d return is scored. */
function tickerOnly1d(): ReactionProfileTicker {
  return {
    symbol: "VLO",
    reaction_profile_basis: "same_day_fallback",
    return_1d: -0.9,
    return_5d: null,
    return_20d: null,
    return_60d: null,
    benchmark_relative_return_1d: -0.4,
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

/** Nothing scorable at any horizon. */
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

/** Peak lands on the final observed session of the 20d window. */
function tickerEndpointPeak20d(): ReactionProfileTicker {
  return {
    ...fullTicker(),
    return_20d: 6.0,
    peak_move_20d: 6.0,
    time_to_peak_20d: 20,
    fade_or_hold_label_20d: "hold",
  };
}

describe("active-horizon selection", () => {
  // (1) all three scorable -> active 20d
  it("selects 20d when 20d, 5d and 1d are all scorable", () => {
    expect(resolveActiveHorizon([fullTicker()])).toBe("20d");
  });

  // (2) 20d unavailable -> active 5d
  it("selects 5d when 20d is not scorable but 5d is", () => {
    expect(resolveActiveHorizon([ticker20dInsufficient()])).toBe("5d");
  });

  // (3) only 1d scorable -> active 1d
  it("selects 1d when only the 1d return exists", () => {
    expect(resolveActiveHorizon([tickerOnly1d()])).toBe("1d");
  });

  // (4) nothing scorable -> no active horizon
  it("returns null when no horizon is scorable", () => {
    expect(resolveActiveHorizon([tickerUnscorable()])).toBeNull();
    expect(resolveActiveHorizon([])).toBeNull();
  });

  // (5) partially populated 20d must not count as scorable
  it("does not treat a partially populated 20d object as scorable", () => {
    const partial: ReactionProfileTicker = {
      ...fullTicker(),
      // Label claims hold but the companion numbers are gone.
      peak_move_20d: null,
      time_to_peak_20d: null,
    };
    expect(classifyTickerHorizon(partial, "20d").availability).not.toBe("available");
    expect(resolveActiveHorizon([partial])).toBe("5d");
  });

  // (6) malformed horizon data fails closed
  it("fails closed on malformed horizon data", () => {
    const malformed = {
      ...fullTicker(),
      fade_or_hold_label_20d: "hodl",
      time_to_peak_5d: 999,
    } as ReactionProfileTicker;
    expect(classifyTickerHorizon(malformed, "20d").availability).toBe("unavailable");
    expect(classifyTickerHorizon(malformed, "5d").availability).toBe("unavailable");
    expect(resolveActiveHorizon([malformed])).toBe("1d");

    const noBasis = { ...fullTicker(), reaction_profile_basis: null };
    expect(classifyTickerHorizon(noBasis, "20d").availability).toBe("unavailable");

    expect(classifyTickerHorizon(null, "20d").availability).toBe("unavailable");
    expect(classifyTickerHorizon(undefined, "5d").availability).toBe("unavailable");
  });

  // (10) an unavailable horizon can never become active through interaction
  it("ignores a requested horizon that is not selectable", () => {
    expect(resolveActiveHorizon([ticker20dInsufficient()], "20d")).toBe("5d");
    expect(resolveActiveHorizon([tickerOnly1d()], "20d")).toBe("1d");
    expect(resolveActiveHorizon([tickerUnscorable()], "20d")).toBeNull();
  });

  // (24) a requested horizon carried over from a prior event cannot leak
  it("re-resolves a stale requested horizon against the current tickers", () => {
    // Selection made while viewing an event with a scorable 20d ...
    expect(resolveActiveHorizon([fullTicker()], "20d")).toBe("20d");
    // ... must fall back when the next event has no scorable 20d.
    expect(resolveActiveHorizon([ticker20dInsufficient()], "20d")).toBe("5d");
  });

  it("honors a selectable requested horizon", () => {
    expect(resolveActiveHorizon([fullTicker()], "5d")).toBe("5d");
    expect(resolveActiveHorizon([fullTicker()], "1d")).toBe("1d");
  });

  it("pins the frozen longest-first order and display set", () => {
    expect(ACTIVE_HORIZON_ORDER).toEqual(["20d", "5d", "1d"]);
    expect(FROZEN_DISPLAY_HORIZONS).toEqual(["1d", "5d", "20d"]);
  });
});

describe("horizon availability", () => {
  // (7) all availability states are exposed
  it("describes available, insufficient and structural states", () => {
    const t = ticker20dInsufficient();
    expect(classifyTickerHorizon(t, "5d").availability).toBe("available");
    expect(classifyTickerHorizon(t, "20d").availability).toBe("insufficient");
    expect(classifyTickerHorizon(t, "1d").availability).toBe("structural");
    expect(classifyTickerHorizon(tickerUnscorable(), "20d").availability).toBe("unavailable");
  });

  it("carries an explicit reason when a horizon is not available", () => {
    const insufficient = classifyTickerHorizon(ticker20dInsufficient(), "20d");
    expect(insufficient.reason).toMatch(/insufficient observations/i);

    const stale = classifyTickerHorizon(
      { ...tickerUnscorable(), reaction_profile_basis: "stale" },
      "20d",
    );
    expect(stale.availability).toBe("unavailable");
    expect(stale.reason).toMatch(/stale/i);

    const unscorable = classifyTickerHorizon(tickerUnscorable(), "5d");
    expect(unscorable.reason).toMatch(/no usable cached price path/i);

    const sdf = classifyTickerHorizon(tickerOnly1d(), "5d");
    expect(sdf.availability).toBe("unavailable");
    expect(sdf.reason).toMatch(/same-day fallback/i);
  });

  // (8)/(10) selectability contract used to disable controls
  it("marks only genuinely scorable horizons selectable", () => {
    expect(isHorizonSelectable([fullTicker()], "20d")).toBe(true);
    expect(isHorizonSelectable([ticker20dInsufficient()], "20d")).toBe(false);
    expect(isHorizonSelectable([ticker20dInsufficient()], "5d")).toBe(true);
    expect(isHorizonSelectable([tickerOnly1d()], "5d")).toBe(false);
    expect(isHorizonSelectable([tickerOnly1d()], "1d")).toBe(true);
    expect(isHorizonSelectable([tickerUnscorable()], "1d")).toBe(false);
  });

  // (9) fallback from 20d is stated, not hidden
  it("describes why the active horizon fell back from 20d", () => {
    expect(describeHorizonFallback([ticker20dInsufficient()], "5d")).toBe(
      "Showing 5d — 20d has insufficient observations for this event.",
    );
    expect(describeHorizonFallback([tickerOnly1d()], "1d")).toBe(
      "Showing 1d — 20d and 5d are unavailable for this event.",
    );
    expect(describeHorizonFallback([fullTicker()], "20d")).toBeNull();
  });

  it("does not describe a user-chosen shorter horizon as a fallback from a scorable 20d", () => {
    // 20d is scorable here; showing 5d is a selection, not a fallback.
    expect(describeHorizonFallback([fullTicker()], "5d")).toBeNull();
  });
});

describe("classification basis", () => {
  // (11) raw-price-path basis is the label's stated source
  it("names the classification as a raw-price path read", () => {
    expect(RAW_PATH_CLASSIFICATION_LABEL).toBe("Raw-price path classification");
    expect(RAW_PATH_BASIS_NOTE).toMatch(/raw price path/i);
    // (12) benchmark-relative views are comparisons, not the label source
    expect(RAW_PATH_BASIS_NOTE).toMatch(/not the source/i);
  });

  // (13) basis disagreement is detected from supplied fields only
  it("detects sign disagreement between raw and benchmark-relative returns", () => {
    expect(detectBasisDisagreement(fullTicker(), "5d")).toBe(true);
    expect(detectBasisDisagreement(fullTicker(), "20d")).toBe(false);
    expect(detectBasisDisagreement(fullTicker(), "1d")).toBe(false);
  });

  // (14) basis agreement never becomes a score — the detector is boolean
  // per basis pair and there is no aggregate/confidence output anywhere.
  it("exposes no consensus, vote or score shape", () => {
    const disagreement = detectHorizonDisagreement(fullTicker());
    expect(Object.keys(disagreement).sort()).toEqual([
      "availableLabels",
      "mixed",
      "states",
    ]);
  });

  // (15) missing basis fields stay unavailable
  it("returns false when either basis value is missing", () => {
    const noBench: ReactionProfileTicker = {
      ...fullTicker(),
      benchmark_relative_return_5d: null,
    };
    expect(detectBasisDisagreement(noBench, "5d")).toBe(false);
    expect(detectBasisDisagreement(tickerUnscorable(), "20d")).toBe(false);
  });
});

describe("horizon disagreement", () => {
  // (16) differing available labels -> mixed
  it("flags mixed classifications across available horizons", () => {
    const d = detectHorizonDisagreement(fullTicker());
    expect(d.mixed).toBe(true);
    expect(d.availableLabels).toEqual(["fade", "hold"]);
    expect(MIXED_HORIZONS_LABEL).toBe("Mixed across horizons");
  });

  // (17) agreeing horizons remain individually visible
  it("keeps agreeing horizons listed individually", () => {
    const agree: ReactionProfileTicker = {
      ...fullTicker(),
      return_5d: 3.2,
      peak_move_5d: 4.0,
      fade_or_hold_label_5d: "hold",
    };
    const d = detectHorizonDisagreement(agree);
    expect(d.mixed).toBe(false);
    const visible = d.states.filter((s) => s.availability === "available");
    expect(visible.map((s) => s.horizon)).toEqual(["5d", "20d"]);
    expect(visible.map((s) => s.label)).toEqual(["hold", "hold"]);
  });

  // (18) unavailable horizons are excluded from the arithmetic but stay visible
  it("excludes non-available horizons from agreement arithmetic while keeping their states", () => {
    const d = detectHorizonDisagreement(ticker20dInsufficient());
    expect(d.availableLabels).toEqual(["fade"]);
    expect(d.mixed).toBe(false);
    const by = Object.fromEntries(d.states.map((s) => [s.horizon, s.availability]));
    expect(by["20d"]).toBe("insufficient");
    expect(by["1d"]).toBe("structural");
  });

  // (19) no majority vote or consensus label exists
  it("never computes a winning label", () => {
    const d = detectHorizonDisagreement(fullTicker());
    expect(d).not.toHaveProperty("consensus");
    expect(d).not.toHaveProperty("winner");
    expect(d).not.toHaveProperty("majority");
  });

  it("includes a scorable 60d classification instead of hiding it", () => {
    const with60: ReactionProfileTicker = {
      ...fullTicker(),
      return_60d: -1.0,
      peak_move_60d: 4.0,
      time_to_peak_60d: 41,
      fade_or_hold_label_60d: "reverse",
    };
    const d = detectHorizonDisagreement(with60);
    expect(d.availableLabels).toEqual(["fade", "hold", "reverse"]);
    expect(d.mixed).toBe(true);
  });

  it("keeps 1d structurally outside classification arithmetic", () => {
    expect(NO_CLASSIFICATION_AT_1D).toMatch(/1d/);
    const d = detectHorizonDisagreement(tickerOnly1d());
    expect(d.availableLabels).toEqual([]);
    expect(d.mixed).toBe(false);
  });
});

describe("endpoint peak / right-censoring", () => {
  // (20) final-session peak -> right-censored
  it("flags a peak on the final observed session", () => {
    expect(isEndpointPeakRightCensored(tickerEndpointPeak20d(), "20d")).toBe(true);
    expect(HORIZON_FORWARD_BARS["20d"]).toBe(20);
    expect(HORIZON_FORWARD_BARS["5d"]).toBe(5);
  });

  // (21) non-final peak -> no qualifier
  it("does not flag an interior peak", () => {
    expect(isEndpointPeakRightCensored(fullTicker(), "20d")).toBe(false);
    expect(isEndpointPeakRightCensored(fullTicker(), "5d")).toBe(false);
  });

  it("never flags when time-to-peak is missing or the horizon is 1d", () => {
    expect(isEndpointPeakRightCensored(tickerUnscorable(), "20d")).toBe(false);
    expect(isEndpointPeakRightCensored(fullTicker(), "1d")).toBe(false);
  });

  // (22)/(23) the qualifier is first-class wording, engine label stays traceable
  it("pins the right-censoring qualifier copy", () => {
    expect(RIGHT_CENSORED_LABEL).toBe("Endpoint peak / right-censored");
    expect(RIGHT_CENSORED_NOTE).toBe(
      "No post-peak path is available inside this horizon.",
    );
    const state = classifyTickerHorizon(tickerEndpointPeak20d(), "20d");
    expect(state.rightCensored).toBe(true);
    expect(state.label).toBe("hold"); // engine label preserved for traceability
  });
});

describe("null and malformed safety", () => {
  // (24)/(25) no NaN / undefined / stale leakage in the pure layer
  it("collapses non-finite numerics to null", () => {
    const weird = {
      ...fullTicker(),
      return_5d: Number.NaN,
      benchmark_relative_return_5d: Number.POSITIVE_INFINITY,
    } as ReactionProfileTicker;
    const s = classifyTickerHorizon(weird, "5d");
    expect(s.availability).toBe("unavailable");
    expect(s.rawReturn).toBeNull();
    expect(s.benchmarkRelativeReturn).toBeNull();
    expect(detectBasisDisagreement(weird, "5d")).toBe(false);
  });

  it("treats a missing ticker list as no active horizon", () => {
    expect(resolveActiveHorizon(undefined as unknown as ReactionProfileTicker[])).toBeNull();
  });

  it("copy constants carry no claim language", () => {
    const copy = [
      RAW_PATH_CLASSIFICATION_LABEL,
      RAW_PATH_BASIS_NOTE,
      RIGHT_CENSORED_LABEL,
      RIGHT_CENSORED_NOTE,
      MIXED_HORIZONS_LABEL,
      BASIS_SENSITIVE_LABEL,
      NO_CLASSIFICATION_AT_1D,
    ].join(" ").toLowerCase();
    for (const banned of [
      "buy", "sell", "signal", "opportunity", "alpha", "predictive",
      "statistically significant", "caused", "validated", "confirmed",
      "best horizon", "strongest horizon", "winning basis", "consensus",
      "confidence",
    ]) {
      expect(copy).not.toContain(banned);
    }
  });
});
