/**
 * T5A — Evidence Overview page.
 *
 * Surfaces the T2/T3/T4 baseline research honestly: the corpus snapshot, the
 * marginal-preserving baseline (T2A), the degenerate primary-only AR-sign
 * (T2B), the multi-ticker AR result (T3A), and the exposed-name coverage
 * limitation (T4A) — with the standing non-claims visible.  Descriptive
 * archive evidence, never a trading or prediction surface.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom).  Since H3 the page
 * consumes GET /evidence/mission-g via React Query, so the render is wrapped in
 * a QueryClientProvider.  The baseline render leaves that query unseeded — the
 * Mission G card shows its honest loading state — so the T2–K3B section
 * assertions below are unaffected by the async record; a separately-seeded
 * render (bottom of file) exercises the Mission G card with contract data.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { EvidenceOverview } from "../evidence-overview";
import { Sidebar } from "@/components/layout/sidebar";
import { qk } from "@/lib/queryKeys";
import type { MissionGEvidenceSummary } from "@/lib/api";

/** Deterministic client for static renders: no retries, nothing goes stale. */
function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity },
    },
  });
}

function renderOverview(client: QueryClient): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <EvidenceOverview />
    </QueryClientProvider>,
  );
}

// Baseline render: the Mission G query is unseeded, so the card shows its
// honest loading state and the static research sections render as before.
const html = renderOverview(testQueryClient());
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

describe("EvidenceOverview — mechanism-family evidence inventory (E2)", () => {
  it("renders the mechanism-family evidence inventory section", () => {
    expect(visible).toContain("Mechanism-family evidence inventory");
    const lc = visible.toLowerCase();
    expect(lc).toContain("accepted track-record lens");
    expect(lc).toContain("descriptive inventory");
  });

  it("renders all six family names", () => {
    for (const fam of [
      "supply_shock", "geopolitical_conflict_context", "tariff",
      "sanction", "ceasefire_deescalation", "monetary_policy_or_rates",
    ]) {
      expect(visible).toContain(fam);
    }
  });

  it("renders the six support / contradiction / unresolved splits", () => {
    for (const sp of ["11 / 3 / 6", "7 / 2 / 2", "5 / 0 / 6", "0 / 0 / 4", "2 / 0 / 1", "1 / 0 / 2"]) {
      expect(visible).toContain(sp);
    }
  });

  it("renders the six event-study coverage figures", () => {
    for (const es of ["20 / 20", "10 / 11", "8 / 11", "1 / 4", "2 / 3"]) {
      expect(visible).toContain(es);
    }
  });

  it("ties the supply_shock row figures together (family, n, split, event-study)", () => {
    expect(visible).toContain("supply_shock 20 11 / 3 / 6 20 / 20");
  });

  it("renders the single / multi / unclassified sum-invariant line", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("single-match 52");
    expect(lc).toContain("multi-match 16");
    expect(lc).toContain("unclassified 18");
    expect(visible).toContain("86");
  });

  it("renders representative case ids labeled illustrative", () => {
    expect(visible).toContain("29, 38, 210");        // supply_shock
    expect(visible).toContain("153, 154, 211");      // sanction
    expect(visible.toLowerCase()).toContain("illustrative case ids");
  });

  it("marks the two overlay-only buckets", () => {
    expect(visible.toLowerCase()).toContain("overlay-only");
    // the overlay-only caveat lists exactly the two overlay families
    expect(visible).toContain("geopolitical_conflict_context, monetary_policy_or_rates");
  });

  it("states staged candidates are excluded", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("staged candidates");
    expect(lc).toContain("excluded");
  });

  it("frames sectors as descriptive hints only", () => {
    expect(visible.toLowerCase()).toContain("descriptive hint");
  });

  it("introduces no proof / forecast / ranking framing in the new section", () => {
    const lc = visible.toLowerCase();
    for (const w of ["proof", "proven", "statistically significant", "trading signal", "forecast", "alpha"]) {
      expect(lc, `banned word "${w}"`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
    for (const phrase of ["validated-as-success", "best family", "strongest family", "outperforming"]) {
      expect(lc, `banned phrase "${phrase}"`).not.toContain(phrase);
    }
  });

  it("reconciles its lens against the other two mechanism-family cards on the page", () => {
    const lc = visible.toLowerCase();
    // disambiguate from the T7B-A grouping card (the sharpest collision:
    // supply_shock 20-vs-3, tariff 11-vs-13) and the AZ1 coverage card
    expect(lc).toContain("different lenses, not competing estimates");
    expect(lc).toContain("market-scored snapshot");
  });

  it("keeps the D1 denominator ledger rendering", () => {
    expect(visible).toContain("Canonical denominators");
  });

  it("does not pull Section C demo content into the overview", () => {
    expect(visible).not.toContain("Demo · Read-only");
  });
});

describe("EvidenceOverview — representative case library (F3)", () => {
  it("renders the representative case library section", () => {
    expect(visible).toContain("Representative case library");
    expect(visible.toLowerCase()).toContain("illustrative");
  });

  it("renders the summary numbers", () => {
    expect(visible).toContain("15 illustrative cases across 6 mechanism families");
    expect(visible).toContain("6 already-covered");
    expect(visible).toContain("9 newly proposed");
    expect(visible).toContain("12 / 15");   // event-study readout
    expect(visible).toContain("6 / 6");      // families represented
  });

  it("renders all 15 case ids", () => {
    for (const id of [1, 46, 61, 66, 210, 211, 7, 29, 38, 71, 153, 154, 160, 212, 239]) {
      expect(visible, `case id #${id}`).toContain(`#${id}`);
    }
  });

  it("ties one anchor row per family together (id, role, family, outcome, event-study)", () => {
    expect(visible).toContain("#210 already-covered anchor supply_shock unresolved yes");
    expect(visible).toContain("#61 already-covered anchor geopolitical_conflict_context contradiction yes");
    expect(visible).toContain("#1 already-covered anchor tariff support yes");
    expect(visible).toContain("#211 already-covered anchor sanction unresolved yes");
    expect(visible).toContain("#66 already-covered anchor ceasefire_deescalation support yes");
    expect(visible).toContain("#46 already-covered anchor monetary_policy_or_rates support yes");
  });

  it("labels new cases as newly proposed and ties their rows", () => {
    expect(visible.toLowerCase()).toContain("newly proposed");
    expect(visible).toContain("#38 newly proposed supply_shock support yes");
    expect(visible).toContain("#153 newly proposed sanction unresolved no");
  });

  it("marks missing-readout cases explicitly (153, 154, 160)", () => {
    expect(visible.toLowerCase()).toContain("missing readout");
    expect(visible).toContain("#153 newly proposed sanction unresolved no");
    expect(visible).toContain("#154 newly proposed sanction unresolved no");
    expect(visible).toContain("#160 newly proposed ceasefire_deescalation unresolved no");
  });

  it("marks thin-family and overlay-only cases", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("thin family");
    expect(lc).toContain("overlay-only");
  });

  it("renders the readout-vs-outcome lens warning", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("readout availability is not the same as thesis support");
    expect(lc).toContain("thesis-direction scoring");
    expect(lc).toContain("primary ticker vs spy");
  });

  it("renders the source line pointing at both reports", () => {
    expect(visible).toContain("stats/REPRESENTATIVE_CASE_EXPANSION.md");
    expect(visible).toContain("stats/EXPANDED_CASE_NOTES.md");
  });

  it("keeps the D1 denominator ledger and E2 inventory rendering", () => {
    expect(visible).toContain("Canonical denominators");
    expect(visible).toContain("Mechanism-family evidence inventory");
  });

  it("introduces no banned framing in the new section", () => {
    const lc = visible.toLowerCase();
    for (const w of ["proof", "proven", "statistically significant", "trading signal", "forecast", "alpha"]) {
      expect(lc, `banned word "${w}"`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
    for (const phrase of ["validated-as-success", "best case", "strongest case", "outperforming"]) {
      expect(lc, `banned phrase "${phrase}"`).not.toContain(phrase);
    }
  });

  it("does not pull Section C demo content into the overview", () => {
    expect(visible).not.toContain("Demo · Read-only");
  });
});

describe("EvidenceOverview — effective independent evidence (K3B)", () => {
  it("renders the effective independent evidence card", () => {
    expect(visible).toContain("Effective independent evidence");
  });

  it("shows the 86 nominal accepted track-record rows", () => {
    expect(visible).toContain("86");
    expect(visible.toLowerCase()).toContain("accepted track-record rows");
  });

  it("shows 7 descriptive market-story clusters", () => {
    expect(visible).toContain("7");
    expect(visible.toLowerCase()).toContain("descriptive market-story clusters");
  });

  it("shows the largest cluster of 79 rows", () => {
    expect(visible).toContain("79");
    expect(visible.toLowerCase()).toContain("largest cluster");
  });

  it("shows 12 / 15 representative cases in the largest cluster", () => {
    expect(visible).toContain("12 / 15");
    expect(visible.toLowerCase()).toContain("representative cases");
  });

  it("explains clustered evidence, not 86 separate market stories", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("clustered evidence");
    expect(lc).toContain("not 86 separate market stories");
  });

  it("references the K2 report path", () => {
    expect(visible).toContain("stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md");
  });

  it("carries the descriptive independence-caution non-claim", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("descriptive independence-caution");
    expect(lc).toContain("not an inferential effective sample size");
    expect(lc).toContain("score");
    expect(lc).toContain("rank");
    expect(lc).toContain("p-value");
    expect(lc).toContain("fdr pool");
    // House copy rule (matching the rest of the page): convey the trading /
    // prediction / recommendation non-claim WITHOUT the banned standalone
    // words "signal" / "forecast".
    expect(lc).toContain("not a trading, prediction, or recommendation surface");
  });

  it("introduces no banned affirmative framing in the new card", () => {
    const lc = visible.toLowerCase();
    for (const w of [
      "proof", "proven", "statistically significant", "trading signal",
      "alpha", "forecast", "predictive", "performance",
    ]) {
      expect(lc, `banned word "${w}"`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });

  it("keeps the denominator ledger and existing cards rendering", () => {
    expect(visible).toContain("Canonical denominators");
    expect(visible).toContain("Mechanism-family evidence inventory");
    expect(visible).toContain("Representative case library");
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

// ---------------------------------------------------------------------------
// H3/H4 — Mission G historical-evidence card, integrated on the page.
//
// The card renders only endpoint-supplied values (H2 contract), so seeding the
// React Query cache with a contract-shaped fixture is what exercises it.  The
// fixture mirrors GET /evidence/mission-g and is the only place these values
// live.  Kept as a separate seeded render so the page-wide banned-word smoke
// tests above keep running against the (loading-state) baseline.
// ---------------------------------------------------------------------------

const APPROVED_OPEC_WORDING =
  "stable descriptive association with unresolved calendar-time confounding";

function missionGFixture(): MissionGEvidenceSummary {
  return {
    contract_version: "mission-g-evidence-v1",
    source_artifacts: {
      readout: "G6_FROZEN_MANIFEST_READOUT.md",
      stability: "G6B_STABILITY_AND_FALSIFIERS.md",
      cases: "G6C_REPRESENTATIVE_CASES.md",
      promotion_proof: "G5_PROMOTION_PROOF.md",
      mechanism_attrition: "G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
    },
    lanes: {
      accepted_track_record: {
        count: 86,
        lane_note:
          "separate immutable live-archive lineage with its own denominator; it is not part of the historical evidence below",
      },
      historical: {
        total: 97,
        fomc_frame_complete: 65,
        opec_designed_contrast: 32,
        lane_note:
          "two historical ledgers promoted under the Mission G protocol; the designed-contrast lane carries no prevalence claim",
      },
      pooling_prohibition:
        "The accepted track record and the historical ledgers are separate denominators answering different questions; they are never pooled, summed, or compared as one sample.",
    },
    main_result: {
      headline:
        "The historical state-conditioning surface is predominantly flat, fragile, or contradictory under the frozen manifest.",
      fomc_null: {
        statement:
          "The frame-complete FOMC lane is broadly null: no state axis holds a stable rank association with any response lens.",
        max_abs_full_sample_rho: 0.2746,
      },
    },
    stability: {
      continuous_associations: 120,
      loeo_sign_reversals: 44,
      loyo_sign_reversals: 76,
      note: "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation",
    },
    bounded_opec_association: {
      wording: APPROVED_OPEC_WORDING,
      axis: "fed_policy_path x sector-relative abnormal return",
      lane: "opec_designed_contrast",
      per_horizon: [
        { horizon: 1, rho: -0.4564, loeo_sign_reversals: 0, loyo_sign_reversals: 0 },
        { horizon: 5, rho: -0.2929, loeo_sign_reversals: 0, loyo_sign_reversals: 0 },
        { horizon: 20, rho: -0.3824, loeo_sign_reversals: 0, loyo_sign_reversals: 0 },
      ],
      confound_note:
        "the state axis itself tracks calendar time inside this lane, so these data cannot separate state from era",
    },
    credit_limitation: {
      available: 36,
      of: 97,
      fomc_subset: 20,
      opec_subset: 16,
      era_bounded: true,
      status: "secondary",
      fragile_associations: 9,
      of_associations: 12,
      note: "HY OAS history before the surviving source window is source-withdrawn; the subset is descriptive only and was not promoted after outcomes were visible",
    },
    failed_thesis_mechanism_comparability: {
      statement:
        "A J1-derived headline mechanism taxonomy did not transfer comparably across accepted news headlines and historical official-decision text; mechanism labels are not a cross-cohort conditioning axis.",
      classification_coverage_percent: {
        accepted_news_headlines: 79.1,
        fomc_official_text: 0.0,
        opec_official_text: 3.1,
      },
    },
    representative_cases: {
      role_slots: 6,
      unique_cases: 6,
      status: "illustrations, never proof",
      selection_note:
        "state-quantile anchored, outcome-blind selection; outcome magnitude was never used",
      cases: [
        { role: "A", lane: "designed_contrast", state_axis: "fed_policy_path", quantile: "q25", candidate_id: "opec-2024-11-03-one-month-delay" },
        { role: "A", lane: "designed_contrast", state_axis: "fed_policy_path", quantile: "q75", candidate_id: "opec-2023-11-30-voluntary-2p2" },
        { role: "B", lane: "designed_contrast", state_axis: "credit_hy_oas", quantile: "q25", candidate_id: "opec-2025-09-07-oct-137k" },
        { role: "B", lane: "designed_contrast", state_axis: "credit_hy_oas", quantile: "q75", candidate_id: "opec-2024-03-03-q2-extension" },
        { role: "C", lane: "frame_complete_historical", state_axis: "fed_policy_path", quantile: "q25", candidate_id: "fomc-policy-decision-2019-09-18" },
        { role: "C", lane: "frame_complete_historical", state_axis: "fed_policy_path", quantile: "q75", candidate_id: "fomc-policy-decision-2018-05-02" },
      ],
    },
    non_claims: [
      "Descriptive research record only: no p-values, no forecasts, no trading interpretation, no single-event inference.",
      "No pooled statistic across evidence lanes.",
      "Representative cases are illustrations, never proof.",
    ],
  };
}

const seededClient = testQueryClient();
seededClient.setQueryData(qk.missionGEvidence(), missionGFixture());
const missionGVisible = renderOverview(seededClient)
  .replace(/<[^>]*>/g, " ")
  .replace(/\s+/g, " ")
  .trim();

describe("EvidenceOverview — Mission G historical-evidence card (H3/H4)", () => {
  it("shows an honest loading state before the record resolves (baseline render)", () => {
    expect(visible.toLowerCase()).toContain(
      "loading the mission g historical record",
    );
  });

  it("surfaces the two-lane architecture with separate denominators, never pooled", () => {
    expect(missionGVisible).toContain("Accepted track record");
    expect(missionGVisible).toContain("Historical evidence");
    expect(missionGVisible).toContain("86"); // accepted lane
    expect(missionGVisible).toContain("97"); // historical total
    expect(missionGVisible).toContain("65"); // FOMC frame-complete
    expect(missionGVisible).toContain("32"); // OPEC designed-contrast
    expect(missionGVisible.toLowerCase()).toContain("never pooled");
  });

  it("never presents a pooled 183 sample", () => {
    expect(missionGVisible).not.toContain("183");
  });

  it("leads with the broad null, then the bounded OPEC association and its confound", () => {
    const lc = missionGVisible.toLowerCase();
    const nullIdx = lc.indexOf("broadly null");
    const opecIdx = missionGVisible.indexOf(APPROVED_OPEC_WORDING);
    expect(nullIdx).toBeGreaterThan(-1);
    expect(opecIdx).toBeGreaterThan(-1);
    expect(nullIdx).toBeLessThan(opecIdx); // the null precedes its one exception
    expect(lc).toContain("cannot separate state from era");
  });

  it("keeps stability reversals and failed/incomplete evidence visible as results", () => {
    expect(missionGVisible).toContain("44/120"); // leave-one-event-out reversals
    expect(missionGVisible).toContain("76/120"); // leave-one-calendar-year-out
    expect(missionGVisible).toContain("36/97");  // era-bounded secondary credit
    expect(missionGVisible).toContain("79.1");   // G3B attrition coverage
    expect(missionGVisible.toLowerCase()).toContain("did not transfer comparably");
  });

  it("lists the representative cases as illustrations, never proof", () => {
    expect(missionGVisible).toContain("illustrations, never proof");
    expect(missionGVisible).toContain("opec-2024-11-03-one-month-delay");
    expect(missionGVisible).toContain("fomc-policy-decision-2018-05-02");
  });

  it("does not fall back to the unavailable/degraded state on a successful load", () => {
    expect(missionGVisible).not.toContain("Mission G record unavailable");
  });
});
