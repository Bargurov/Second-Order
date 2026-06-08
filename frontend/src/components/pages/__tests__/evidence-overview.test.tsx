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
    expect(visible).toContain("71");  // event-study available
    expect(visible).toContain("10");  // event-study unavailable
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
    expect(visible).toContain("63");
    expect(visible).toContain("0.508");
    expect(visible).toContain("0.206");
    expect(visible).toContain("0.222");
    expect(visible.toLowerCase()).toContain("degenerate");
    expect(visible.toLowerCase()).toContain("all beneficiaries");
  });
});

describe("EvidenceOverview — T3A multi-ticker AR (T5A)", () => {
  it("renders the headline figures and the reliable-but-thin status", () => {
    expect(visible).toContain("149");
    expect(visible).toContain("69");
    expect(visible).toContain("0.792");
    expect(visible.toLowerCase()).toContain("reliable but thin");
  });

  it("renders the per-horizon support-vs-null table", () => {
    expect(visible).toContain("0.524");
    expect(visible).toContain("0.440");
    expect(visible).toContain("[0.376, 0.510]");
    expect(visible).toContain("0.302");
    expect(visible).toContain("0.358");
    expect(visible).toContain("0.356");
    expect(visible).toContain("0.326");
  });

  it("states the mixed result honestly without claiming a 1d discovery", () => {
    expect(visible.toLowerCase()).toContain("does not hold at 5d / 20d");
  });
});

describe("EvidenceOverview — T4A coverage limitation (T5A)", () => {
  it("renders the coverage figures and the repair boundary", () => {
    expect(visible).toContain("118 / 216");
    expect(visible).toContain("54.6%");
    expect(visible).toContain("31 / 113");
    expect(visible).toContain("27.4%");
    expect(visible).toContain("149 / 329");
    expect(visible).toContain("45.3%");
    expect(visible.toLowerCase()).toContain("price-cache backfill");
    expect(visible.toLowerCase()).toContain("operator approval");
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

describe("EvidenceOverview — coverage repair plan, not executed (V3A)", () => {
  it("renders the section titled as not executed", () => {
    expect(visible).toContain("Coverage repair plan — not executed");
  });

  it("shows the current unchanged exposed-name limitation", () => {
    expect(visible).toContain("31 / 113");   // loser/exposed coverage (unchanged)
    expect(visible).toContain("149 / 329");  // total coverage (unchanged)
  });

  it("shows the V2A dry-run worklist", () => {
    expect(visible).toContain("180"); // missing units
    expect(visible).toContain("87");  // distinct symbols / est requests
    expect(visible).toContain("171"); // fixable symbol-date windows
    expect(visible).toContain("7,830"); // approximate cache rows
  });

  it("shows the full fixability split", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("backfill_forward");
    expect(visible).toContain("55");
    expect(lc).toContain("gap_fill_maybe");
    expect(visible).toContain("53");
    expect(lc).toContain("backfill_earlier");
    expect(visible).toContain("44");
    expect(lc).toContain("no_cache_backfill");
    expect(visible).toContain("19");
    expect(lc).toContain("alias_manual_review");
    expect(lc).toContain("future_not_yet");
    expect(lc).toContain("delisted_stale");
  });

  it("states the strict V2B gate", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("not executed");
    expect(lc).toContain("confirm_paid");
    expect(lc).toContain("db copy");
    expect(lc).toContain("never mutated first");
  });

  it("states no coverage numbers changed", () => {
    expect(visible.toLowerCase()).toContain("no coverage numbers above have changed");
  });

  it("states representativeness only, not significance or edge", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("representativeness");
    expect(lc).toContain("does not create statistical significance");
    expect(lc).toContain("edge");
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
