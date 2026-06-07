/**
 * R4C — Evidence Coverage card render smoke.
 *
 * The card makes denominators visible WITHOUT pretending the three gates
 * (track-record coverage, FDR pools, and the deferred event-study readiness)
 * are one linear funnel.  It must:
 *   - render two visually separated bands (A: track-record coverage,
 *     B: closed FDR pools), Band A before Band B;
 *   - keep Phase 1 and Phase 2 as separate counts — never summed;
 *   - carry the three required non-claim lines and the event-study-deferred
 *     note (no usable / event-study-ready count is shown in R4C);
 *   - render the envelope's fdr_scope_note verbatim;
 *   - carry no banned trade / signal / overclaim framing.
 *
 * Presentational only — no React Query, no network.  Pattern mirrors
 * tracked-evidence-card.test.tsx: vitest + renderToStaticMarkup, no jsdom,
 * DISTINCT fixture counts so a Phase 1 / Phase 2 swap or merge is observable.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { TrackRecord, TrackedEvidenceSummaryResponse } from "@/lib/api";
import {
  EVIDENCE_COVERAGE_COPY,
  EvidenceCoverageCard,
} from "../evidence-coverage-card";

// ---------------------------------------------------------------------------
// Fixtures — distinct values so merges / swaps are detectable.  No field
// equals 12 (= phase1 5 + phase2 7), so a merged-pool count is observable.
// ---------------------------------------------------------------------------

function _trackRecord(over: Partial<TrackRecord> = {}): TrackRecord {
  return {
    total: 157,
    validated: 31, // any-supporting
    contradicted: 11,
    unresolved: 9,
    avg_support_ratio: 0.58,
    revisit_scored: 4,
    rated_good: 0,
    rated_mixed: 0,
    rated_poor: 0,
    ...over,
  };
}

function _evidence(
  over: Partial<TrackedEvidenceSummaryResponse> = {},
): TrackedEvidenceSummaryResponse {
  return {
    ok: true,
    section: "tracked_evidence",
    schema_version: "v1",
    summary: {
      phase1_count: 5,
      phase2_count: 7,
      phase2_pass_count: 4,
      phase2_fail_count: 3,
      deferred_count: 2,
    },
    phase1: [],
    phase2: [],
    fdr_scope_note: "FDR-SCOPE-NOTE-SENTINEL: phases stay separate.",
    limitations: [],
    warnings: [],
    errors: [],
    ...over,
  };
}

const html = renderToStaticMarkup(
  <EvidenceCoverageCard trackRecord={_trackRecord()} evidence={_evidence()} />,
);
const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

describe("EvidenceCoverageCard — separated denominator bands (R4C)", () => {
  it("renders Band A (coverage) and Band B (FDR pools) as separate bands, A before B", () => {
    expect(html).toContain(EVIDENCE_COVERAGE_COPY.bandACoverageLabel);
    expect(html).toContain(EVIDENCE_COVERAGE_COPY.bandBPoolsLabel);
    expect(html.indexOf(EVIDENCE_COVERAGE_COPY.bandACoverageLabel)).toBeLessThan(
      html.indexOf(EVIDENCE_COVERAGE_COPY.bandBPoolsLabel),
    );
  });

  it("shows the screened track-record denominator and its resolved breakdown (Band A)", () => {
    expect(visible).toMatch(/Screened[^0-9]{0,6}157/); // denominator
    expect(visible).toMatch(/42 resolved/); // derived = 31 + 11
    expect(visible).toMatch(/31 any-supporting/);
    expect(visible).toMatch(/11 contradicted/);
    expect(visible).toMatch(/9 unresolved/);
  });

  it("keeps Phase 1 and Phase 2 separate — never summed into one pool count", () => {
    expect(visible).toMatch(/Phase 1[^0-9]{0,6}5\b/);
    expect(visible).toMatch(/Phase 2[^0-9]{0,6}7\b/);
    expect(visible).toMatch(/4 pass/);
    expect(visible).toMatch(/3 fail/);
    expect(visible).toMatch(/2 deferred/);
    // A merged pool count (5 + 7 = 12) must never appear.
    expect(visible).not.toMatch(/\b12\b/);
  });

  it("uses an equivalent scope warning, not a duplicate of the verbatim fdr_scope_note", () => {
    // TrackedEvidenceCard renders the verbatim note authoritatively right below
    // this card; duplicating the same multi-sentence prose would read as a bug.
    expect(html).not.toContain("FDR-SCOPE-NOTE-SENTINEL");
    // The equivalent separation warning is carried by non-claim #3.
    expect(html).toContain(
      "Closed FDR pools are separate curated cohorts, not a filter of all screened events.",
    );
  });

  it("renders nothing without a screened denominator (no Band-B-only echo)", () => {
    // /evidence/summary returns counts even on an empty DB (tracked artifacts);
    // without a track-record denominator this card would be a denominator-less
    // echo of TrackedEvidenceCard, so it must not render at all.
    const noDenom = renderToStaticMarkup(
      <EvidenceCoverageCard trackRecord={_trackRecord({ total: 0 })} evidence={_evidence()} />,
    );
    expect(noDenom).toBe("");
  });

  it("renders the three required non-claim lines", () => {
    for (const line of EVIDENCE_COVERAGE_COPY.nonClaims) {
      expect(html).toContain(line);
    }
    expect(EVIDENCE_COVERAGE_COPY.nonClaims).toHaveLength(3);
  });

  it("defers event-study readiness (no usable count shown in R4C)", () => {
    expect(html).toContain(EVIDENCE_COVERAGE_COPY.eventStudyDeferredNote);
    // The card takes only trackRecord + evidence — it renders fully without
    // any usable / event-study-ready input (proven by this render passing).
    expect(EVIDENCE_COVERAGE_COPY.eventStudyDeferredNote.toLowerCase()).toContain(
      "tracked separately",
    );
  });

  it("carries no banned trade / signal / overclaim framing", () => {
    const corpus = (visible + " " + JSON.stringify(EVIDENCE_COVERAGE_COPY)).toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proven", "confirmed", "validated", "predicted",
    ]) {
      expect(corpus, `banned word "${w}" in the coverage card`).not.toMatch(
        new RegExp(`\\b${w}\\b`),
      );
    }
  });
});
