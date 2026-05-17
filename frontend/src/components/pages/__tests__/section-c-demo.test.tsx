/**
 * Acceptance smoke for the Section C Demo page.
 *
 * The frontend test suite runs under Vitest's default ``node``
 * environment with no jsdom — see
 * ``components/__tests__/error-boundary.test.tsx`` for the same
 * pattern.  We render the page via ``react-dom/server`` with a
 * ``QueryClient`` pre-seeded so ``useQuery`` returns the fixture
 * synchronously instead of going through the network path.
 *
 * What this smoke pins
 * --------------------
 *
 *  * The page title and subtitle are present verbatim.
 *  * All four panel headers render (Daily / Weekly / Still Moving /
 *    Evidence Summary).
 *  * A Daily fixture with three items renders each headline.
 *  * The Evidence panel keeps ``fdr_significant_count`` and
 *    ``raw_p_candidate_count`` as distinct surfaces — a raw-p
 *    candidate is not reframed as FDR-significant.
 *  * The Event 60 benchmark sensitivity advisory surfaces when 60
 *    is in ``changed_event_ids``.
 *  * Weekly + Still Moving show their own intentional empty copy
 *    when the API returns ``items: []``.
 *  * The rendered HTML does not leak overclaim vocabulary.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type {
  DemoDailyMarketResponse,
  DemoEvidenceSummaryResponse,
  DemoStillMovingMarketResponse,
  DemoWeeklyMarketResponse,
} from "@/lib/api";
import { COPY } from "@/components/demo/evidence-summary-panel";

import { SectionCDemo } from "../section-c-demo";

// ---------------------------------------------------------------------------
// Fixtures — mirror the shapes the four demo endpoints emit.  Headlines
// match the local artifact bodies so the smoke reads as the deployed
// demo would.
// ---------------------------------------------------------------------------

const dailyFixture: DemoDailyMarketResponse = {
  ok:      true,
  section: "daily",
  count:   3,
  items: [
    {
      candidate_id:     "daily-demo-001",
      headline:         "OPEC extends voluntary oil output cuts through next quarter",
      event_date:       "2026-04-15",
      mechanism_family: "supply_shock",
      primary_ticker:   "XLE",
      benchmark_ticker: "SPY",
      market_relevance: "high",
      inclusion_reason: "Operator-marked artifact-backed candidate.",
      operator_notes:   "Reviewed Daily demo candidate.",
      caution_label:    "demo Daily Market source; operator review required before use",
    },
    {
      candidate_id:     "daily-demo-002",
      headline:         "Saudi Arabia signals deeper voluntary oil export cuts in May",
      event_date:       "2026-04-28",
      mechanism_family: "supply_shock",
      primary_ticker:   "XLE",
      benchmark_ticker: "SPY",
      market_relevance: "high",
      inclusion_reason: "Operator-marked artifact-backed candidate.",
      operator_notes:   "Reviewed Daily demo candidate.",
      caution_label:    "demo Daily Market source; operator review required before use",
    },
    {
      candidate_id:     "daily-demo-003",
      headline:         "Fuel reservoir hit at the Primorsk port after drone attacks",
      event_date:       "2026-04-06",
      mechanism_family: "refined_product_supply_disruption",
      primary_ticker:   "VLO",
      benchmark_ticker: "SPY",
      market_relevance: "medium",
      inclusion_reason: "Operator-marked artifact-backed candidate.",
      operator_notes:   "Reviewed Daily demo candidate.",
      caution_label:    "demo Daily Market source; operator review required before use",
    },
  ],
  skipped_artifacts: [],
  warnings:          [],
  errors:            [],
};

const weeklyEmptyFixture: DemoWeeklyMarketResponse = {
  ok:                         true,
  section:                    "weekly",
  count:                      0,
  items:                      [],
  duplicate_groups_collapsed: 0,
  warnings:                   [],
  errors:                     [],
};

const stillMovingEmptyFixture: DemoStillMovingMarketResponse = {
  ok:                true,
  section:           "still_moving",
  count:             0,
  items:             [],
  rejected_count:    0,
  rejection_summary: {},
  warnings:          [],
  errors:            [],
};

const evidenceFixture: DemoEvidenceSummaryResponse = {
  ok:      true,
  section: "evidence_summary",
  cohort_summary: {
    events_evaluated:           12,
    total_records:              48,
    horizons_covered:           [1, 5, 20],
    mechanism_families_covered: ["supply_shock", "policy_shift"],
  },
  verdict_counts: {
    fdr_significant:      0,
    raw_p_only_candidate: 3,
    inconclusive_fdr:     8,
    insufficient:         1,
  },
  fdr_significant_count: 0,
  raw_p_candidate_count: 3,
  benchmark_sensitivity_status: {
    status:              "comparison_available",
    changed_event_ids:   [60],
    unchanged_event_ids: [55, 71],
  },
  limitations: [
    "raw-p candidate signals are not FDR-significant",
  ],
  warnings: [],
  errors:   [],
};

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

interface SeedOpts {
  daily?:       DemoDailyMarketResponse;
  weekly?:      DemoWeeklyMarketResponse;
  stillMoving?: DemoStillMovingMarketResponse;
  evidence?:   DemoEvidenceSummaryResponse;
}

function renderPage(opts: SeedOpts = {}): string {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (opts.daily)       qc.setQueryData(["demo", "daily-market"],        opts.daily);
  if (opts.weekly)      qc.setQueryData(["demo", "weekly-market"],       opts.weekly);
  if (opts.stillMoving) qc.setQueryData(["demo", "still-moving-market"], opts.stillMoving);
  if (opts.evidence)    qc.setQueryData(["demo", "evidence-summary"],    opts.evidence);
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <SectionCDemo />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Page chrome
// ---------------------------------------------------------------------------

describe("SectionCDemo — page chrome", () => {
  it("renders the page title 'Section C Demo'", () => {
    const html = renderPage();
    expect(html).toContain("Section C Demo");
  });

  it("renders the page subtitle verbatim", () => {
    const html = renderPage();
    expect(html).toContain(
      "Operator-reviewed Daily, Weekly, and Still Moving candidates, plus the pilot-cohort evidence summary.",
    );
  });

  it("renders all four panel headers regardless of fetch state", () => {
    const html = renderPage();
    expect(html).toContain("Daily Market");
    expect(html).toContain("Weekly Market");
    expect(html).toContain("Still Moving Market");
    expect(html).toContain("Evidence Summary");
  });
});

// ---------------------------------------------------------------------------
// Daily — three items render with their headlines
// ---------------------------------------------------------------------------

describe("SectionCDemo — Daily panel", () => {
  it("renders all three Daily items from the fixture", () => {
    const html = renderPage({ daily: dailyFixture });
    for (const item of dailyFixture.items) {
      expect(html).toContain(item.headline);
    }
  });

  it("renders each Daily item's candidate_id", () => {
    const html = renderPage({ daily: dailyFixture });
    expect(html).toContain("daily-demo-001");
    expect(html).toContain("daily-demo-002");
    expect(html).toContain("daily-demo-003");
  });
});

// ---------------------------------------------------------------------------
// Evidence — raw-p vs FDR distinction stays surfaced separately
// ---------------------------------------------------------------------------

describe("SectionCDemo — Evidence panel", () => {
  it("surfaces the FDR-significant count and the raw-p candidate count as distinct stat blocks", () => {
    const html = renderPage({ evidence: evidenceFixture });
    expect(html).toContain("FDR-significant count");
    expect(html).toContain("Raw-p candidate count");
  });

  it("renders the pinned FDR-zero advisory when fdr_significant_count is 0", () => {
    const html = renderPage({ evidence: evidenceFixture });
    expect(html).toContain(COPY.fdrZero);
  });

  it("renders the pinned raw-p caveat when raw_p_candidate_count > 0", () => {
    const html = renderPage({ evidence: evidenceFixture });
    expect(html).toContain(COPY.rawPCaveat);
  });

  it("surfaces the Event 60 benchmark sensitivity advisory when 60 is in changed_event_ids", () => {
    const html = renderPage({ evidence: evidenceFixture });
    expect(html).toContain(COPY.event60);
  });
});

// ---------------------------------------------------------------------------
// Weekly + Still Moving — empty states come from the panel components
// ---------------------------------------------------------------------------

describe("SectionCDemo — intentional empty states", () => {
  it("renders the Weekly panel's empty copy when items is empty", () => {
    const html = renderPage({ weekly: weeklyEmptyFixture });
    expect(html).toContain("No weekly demo items currently.");
  });

  it("renders the Still Moving panel's empty copy when items is empty", () => {
    const html = renderPage({ stillMoving: stillMovingEmptyFixture });
    expect(html).toContain("No eligible Still Moving items currently.");
  });
});

// ---------------------------------------------------------------------------
// Conservative language — the rendered HTML must not carry overclaim
// vocabulary anywhere across the four panels.
// ---------------------------------------------------------------------------

const _BANNED_TOKENS = [
  "proven",
  "validated",
  "alpha generated",
  "causal",
  "guaranteed",
  "production-ready",
  "production ready",
  "demo_ready",
  "demo-ready",
] as const;

describe("SectionCDemo — conservative language", () => {
  it("does not leak any banned overclaim token into the rendered HTML", () => {
    const html = renderPage({
      daily:       dailyFixture,
      weekly:      weeklyEmptyFixture,
      stillMoving: stillMovingEmptyFixture,
      evidence:    evidenceFixture,
    }).toLowerCase();
    for (const token of _BANNED_TOKENS) {
      expect(
        html,
        `banned token "${token}" leaked into the rendered page`,
      ).not.toContain(token);
    }
  });
});
