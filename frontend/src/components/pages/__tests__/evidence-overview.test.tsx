/**
 * T5A — Evidence Overview page.
 *
 * Surfaces the T2/T3/T4 baseline research honestly: the corpus snapshot, the
 * marginal-preserving baseline (T2A), the degenerate primary-only AR-sign
 * (T2B), the multi-ticker AR result (T3A), and the exposed-name coverage
 * limitation (T4A) — with the standing non-claims visible.  Descriptive
 * archive evidence, never a trading or prediction surface.
 *
 * Pure / presentational (no React Query, no jsdom), matching the project's
 * render-smoke pattern (renderToStaticMarkup).
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { EvidenceOverview } from "../evidence-overview";
import { Sidebar } from "@/components/layout/sidebar";

const html = renderToStaticMarkup(<EvidenceOverview />);
const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

describe("EvidenceOverview — title + purpose + corpus snapshot (T5A)", () => {
  it("shows the page title and a research-not-trading purpose line", () => {
    expect(visible).toContain("Evidence Overview");
    expect(visible.toLowerCase()).toContain("descriptive");
    expect(visible.toLowerCase()).toContain("not a trading or prediction surface");
  });

  it("renders the corpus snapshot", () => {
    expect(visible).toContain("81");  // market-scored
    expect(visible).toContain("19");  // any-supporting
    expect(visible).toContain("35");  // contradicted
    expect(visible).toContain("27");  // unresolved
    expect(visible).toContain("78");  // event-study available (post-V2C: 71 -> 78)
  });
});

describe("EvidenceOverview — T2A baseline (T5A)", () => {
  it("renders the not-above-baseline verdict and plain-English interpretation", () => {
    expect(visible).toContain("19.2");
    expect(visible).toContain("[13, 26]");
    expect(visible).toContain("not_above_baseline");
    expect(visible.toLowerCase()).toContain("indistinguishable from a marginal-preserving naive baseline");
  });
});

describe("EvidenceOverview — T2B primary-only AR-sign (T5A)", () => {
  it("renders the SPY/63 figures and the degenerate-null explanation", () => {
    expect(visible).toContain("SPY");
    expect(visible).toContain("70");
    expect(visible).toContain("0.500");
    expect(visible).toContain("0.214");
    expect(visible).toContain("0.200");
    expect(visible.toLowerCase()).toContain("degenerate");
    expect(visible.toLowerCase()).toContain("all beneficiaries");
  });
});

describe("EvidenceOverview — T3A multi-ticker AR (T5A)", () => {
  it("renders the post-V2C headline figures and the no-longer-thin status", () => {
    expect(visible).toContain("292");
    expect(visible).toContain("72");
    expect(visible).toContain("0.675");
    expect(visible.toLowerCase()).toContain("no longer thin");
  });

  it("renders the per-horizon support-vs-null table (promoted-live)", () => {
    expect(visible).toContain("0.531");
    expect(visible).toContain("0.455");
    expect(visible).toContain("[0.401, 0.503]");
    expect(visible).toContain("0.339");
    expect(visible).toContain("0.422");
    expect(visible).toContain("0.397");
    expect(visible).toContain("0.399");
  });

  it("states the mixed result honestly without claiming a 1d discovery", () => {
    expect(visible.toLowerCase()).toContain("does not hold at 5d / 20d");
  });
});

describe("EvidenceOverview — T4A coverage limitation (T5A)", () => {
  it("renders the promoted-live coverage figures and the repaired boundary", () => {
    expect(visible).toContain("197 / 216");
    expect(visible).toContain("91.2%");
    expect(visible).toContain("95 / 113");
    expect(visible).toContain("84.1%");
    expect(visible).toContain("292 / 329");
    expect(visible).toContain("88.8%");
    expect(visible.toLowerCase()).toContain("repaired");
    expect(visible.toLowerCase()).toContain("additive");
  });
});

describe("EvidenceOverview — mechanism-family breakdown (T7B-A)", () => {
  it("renders the deterministic scored family distribution", () => {
    expect(visible).toContain("57"); // non-none of 81
    expect(visible.toLowerCase()).toContain("commodity_squeeze");
    expect(visible).toContain("26");
    expect(visible.toLowerCase()).toContain("tariff");
    expect(visible).toContain("13");
    expect(visible.toLowerCase()).toContain("sanction");
    expect(visible).toContain("9");
    expect(visible.toLowerCase()).toContain("supply_shock");
    expect(visible.toLowerCase()).toContain("industrial_policy");
    expect(visible.toLowerCase()).toContain("ceasefire_deescalation");
    expect(visible.toLowerCase()).toContain("policy_surprise");
  });

  it("shows the none / unclassified count honestly", () => {
    expect(visible.toLowerCase()).toContain("none");
    expect(visible).toContain("24");
  });

  it("labels it as deterministic inference, not paid extraction", () => {
    expect(visible).toContain("Deterministic mechanism-family inference — keyword/asset based, not paid structured extraction.");
  });

  it("caveats that it is a grouping, not a channel taxonomy or falsifier layer", () => {
    expect(visible).toContain("This is a family grouping, not a first/second-order channel taxonomy or falsifier layer.");
  });
});

describe("EvidenceOverview — how to read the event-study rows (U2)", () => {
  it("renders the methodology section title", () => {
    expect(visible).toContain("How to read the event-study rows");
  });

  it("defines Raw / Bench / AR / CAR / SAR", () => {
    expect(visible).toContain("Raw");
    expect(visible).toContain("Bench");
    expect(visible).toMatch(/\bAR\b/);
    expect(visible).toMatch(/\bCAR\b/);
    expect(visible).toMatch(/\bSAR\b/);
    const lc = visible.toLowerCase();
    expect(lc).toContain("abnormal return");
    expect(lc).toContain("cumulative abnormal return");
    expect(lc).toContain("standardized abnormal return");
  });

  it("states SAR is a ratio, not a percent", () => {
    expect(visible.toLowerCase()).toContain("ratio, not a percent");
  });

  it("states the SPY benchmark, 1d / 5d / 20d horizons, and 60-bar estimation window", () => {
    expect(visible).toContain("SPY");
    expect(visible).toContain("1d / 5d / 20d");
    expect(visible).toContain("60");
    expect(visible.toLowerCase()).toContain("estimation window");
  });

  it("states the n = 1 single-event limits, not statistical significance", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("n = 1");
    expect(lc).toContain("not statistical significance");
  });

  it("states no CI / p-value / FDR at the single-event level", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("confidence interval");
    expect(lc).toContain("p-value");
    expect(lc).toContain("false-discovery");
  });

  it("states the Phase 1 / Phase 2 FDR pools are a separate track", () => {
    expect(visible.toLowerCase()).toContain("phase 1 / phase 2 fdr pools are a separate");
  });

  it("states the definitions add no new claim", () => {
    expect(visible.toLowerCase()).toContain("add no new claim");
  });
});

describe("EvidenceOverview — coverage repair executed (V2C)", () => {
  it("renders the section titled as executed", () => {
    expect(visible).toContain("Coverage repair — executed");
  });

  it("shows the promoted-live coverage and the rows inserted", () => {
    expect(visible).toContain("95 / 113");   // loser/exposed coverage (now)
    expect(visible).toContain("292 / 329");  // total coverage (now)
    expect(visible).toContain("8,538");      // additive rows promoted into live
  });

  it("shows the residual (still-missing) worklist", () => {
    expect(visible).toContain("37"); // remaining missing units
    expect(visible).toContain("26"); // remaining distinct symbols
    expect(visible).toContain("28"); // remaining windows
  });

  it("shows the residual fixability split", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("gap_fill_maybe");
    expect(lc).toContain("no_cache_backfill");
    expect(lc).toContain("alias_manual_review");
    expect(lc).toContain("future_not_yet");
    expect(lc).toContain("delisted_stale");
  });

  it("states the additive, price_cache-only promotion", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("executed");
    expect(lc).toContain("additive");
    expect(lc).toContain("only price_cache");
  });

  it("states the conclusion is unchanged and the clustering ceiling is not lifted", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("representativeness");
    expect(lc).toContain("does not create statistical significance");
    expect(lc).toContain("edge");
    expect(lc).toContain("clustering");
  });
});

describe("EvidenceOverview — non-claims visible (T5A)", () => {
  it("renders every standing non-claim", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("descriptive archive characterization only");
    expect(lc).toContain("not a trading or prediction surface");
    expect(lc).toContain("not a measure of edge");
    expect(lc).toContain("not a statistical-significance");
    expect(lc).toContain("n = 1 point estimates");
    expect(lc).toContain("date-clustered");
    expect(lc).toContain("separate from the closed phase 1 / phase 2 fdr pools");
  });
});

describe("EvidenceOverview — no banned framing (T5A)", () => {
  it("carries no buy / sell / trade / signal / overclaim framing", () => {
    const lc = visible.toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed",
    ]) {
      expect(lc, `banned word "${w}" on the Evidence Overview page`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});

describe("EvidenceOverview — navigation (T5A)", () => {
  it("appears under the Research group in the sidebar", () => {
    const nav = renderToStaticMarkup(<Sidebar current="market" onNavigate={() => {}} />);
    const navVisible = nav.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    expect(navVisible).toContain("Evidence Overview");
    expect(navVisible).toContain("Research");
  });
});
