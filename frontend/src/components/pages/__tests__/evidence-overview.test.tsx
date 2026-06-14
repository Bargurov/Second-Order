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

  it("renders the dated (2026-06-08) corpus snapshot", () => {
    // RESEARCH_FINDINGS is a coherent as-of-2026-06-08 snapshot (the T2/T3/T4
    // baselines below cannot be recomputed here), so its corpus figures stay
    // at their real date rather than being half-updated.
    expect(visible).toContain("81");  // market-scored
    expect(visible).toContain("19");  // any-supporting
    expect(visible).toContain("35");  // contradicted
    expect(visible).toContain("27");  // unresolved
    expect(visible).toContain("78");  // event-study available (post-V2C: 71 -> 78)
    expect(visible).toContain("2026-06-08");  // the snapshot date is shown
  });

  it("shows the current accepted-corpus restatement (post-AP3b, 2026-06-09)", () => {
    expect(visible).toContain("180");  // saved events (current)
    expect(visible).toContain("86");   // accepted track-record total (current)
    expect(visible).toContain("94");   // coverage / analysis denominator (current)
    expect(visible.toLowerCase()).toContain("restated");
    expect(visible.toLowerCase()).toContain("flagged");   // synthetic seeds flagged
    expect(visible.toLowerCase()).toContain("excluded");  // ...and excluded
    expect(visible).toContain("2026-06-09");              // restatement date
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

describe("EvidenceOverview — mechanism-family coverage: accepted vs staged (AZ1)", () => {
  it("renders the accepted-vs-staged coverage card with its taxonomy framing", () => {
    expect(visible).toContain("Mechanism-family coverage");
    const lc = visible.toLowerCase();
    expect(lc).toContain("research taxonomy, not a causal claim");
  });

  it("separates the staged candidate count from the accepted denominators", () => {
    expect(visible).toContain("Staged candidates (excluded from accepted) 13");
    const lc = visible.toLowerCase();
    expect(lc).toContain("not accepted evidence");
    expect(lc).toContain("never enter accepted denominators");
  });

  it("shows the thin accepted family evidence and the untagged limitation", () => {
    expect(visible).toContain("tariff 4 · sanction 4");
    const lc = visible.toLowerCase();
    expect(lc).toContain("curated observations");
    expect(lc).toContain("untagged");
  });

  it("names the Tier-1 staged/no-paid bridge candidates", () => {
    expect(visible).toContain("#303");
    expect(visible).toContain("#304");
    expect(visible).toContain("#313");
    const lc = visible.toLowerCase();
    expect(lc).toContain("regulation");
    expect(lc).toContain("labor_inflation");
    expect(lc).toContain("industrial_policy");
    expect(lc).toContain("weak event-date caveat");
  });

  it("keeps representative cases illustrative, not evidence", () => {
    expect(visible.toLowerCase()).toContain("illustrative, not evidence");
  });

  it("shows the read-only reproduce command and names both research notes", () => {
    expect(visible).toContain(
      "python scripts/mechanism_family_overview_report.py --db-path events.db --json",
    );
    expect(visible).toContain("stats/MECHANISM_FAMILY_OVERVIEW.md");
    expect(visible).toContain("stats/STAGED_CANDIDATE_SHORTLIST.md");
  });
});

describe("EvidenceOverview — canonical denominator ledger (D1)", () => {
  it("renders the denominator ledger / evidence funnel section", () => {
    expect(visible).toContain("Canonical denominators");
    const lc = visible.toLowerCase();
    expect(lc).toContain("denominator ledger");
    // the carousel cure: state that different denominators answer different questions
    expect(lc).toContain("different denominator");
    expect(lc).toContain("different question");
  });

  it("shows all five canonical funnel numbers with their labels", () => {
    expect(visible).toContain("180");
    expect(visible.toLowerCase()).toContain("archive rows");
    expect(visible).toContain("94");
    expect(visible.toLowerCase()).toContain("accepted coverage rows");
    expect(visible).toContain("86");
    expect(visible.toLowerCase()).toContain("accepted track-record rows");
    expect(visible).toContain("78 / 94"); // event-study available, paired with its denominator
    expect(visible.toLowerCase()).toContain("event-study available");
    expect(visible).toContain("13");
    expect(visible.toLowerCase()).toContain("staged candidates");
  });

  it("keeps staged candidates explicitly separate from the accepted / FDR pools", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("outside the accepted and fdr pools");
    expect(lc).toContain("never");
    expect(lc).toContain("accepted denominators");
  });

  it("frames event-study availability as coverage, not significance", () => {
    expect(visible.toLowerCase()).toContain("coverage denominator, not a significance claim");
  });

  it("keeps representative cases illustrative, not evidence (no proof framing)", () => {
    expect(visible.toLowerCase()).toContain("illustrative, not evidence");
  });

  it("labels the pre-restatement snapshot as superseded / AP3b-era", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("superseded");
    expect(lc).toContain("ap3b-era");
  });

  it("introduces no forecast / proven / trading-signal / validated-as-success framing", () => {
    const lc = visible.toLowerCase();
    expect(lc).not.toMatch(/\bforecast\b/);
    expect(lc).not.toMatch(/\bproven\b/);
    expect(lc).not.toMatch(/trading[\s-]?signal/);
    expect(lc).not.toMatch(/validated[\s-]?as[\s-]?success/);
  });

  it("does not pull Section C demo content into the research overview", () => {
    // The demo Evidence Summary panel (Section C) is decoupled (pure API
    // projection, no accepted-corpus import); its signature eyebrow must
    // never appear on this research page.
    expect(visible).not.toContain("Demo · Read-only");
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
