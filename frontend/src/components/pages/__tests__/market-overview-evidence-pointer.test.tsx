/**
 * M1 — clean-clone reviewer pointer on Market Overview.
 *
 * A clean clone has an EMPTY local archive while the published tracked
 * evidence record (GET /evidence/summary, tracked artifacts) is available —
 * which is exactly the state that suppresses the true cold-start panel
 * (isColdStart requires no tracked evidence). The reviewer pointer must be
 * visible in that real clean-clone state, appear exactly once, navigate
 * through the central navigate("evidence") contract (wired by App), and
 * never blur the line between the empty live archive and the published
 * descriptive research record.
 *
 * Pure visibility helper + seeded render smokes (renderToStaticMarkup,
 * no jsdom, matching the project pattern).
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  MarketOverview,
  showEvidenceReviewerPointer,
  EVIDENCE_POINTER_NOTE,
  EVIDENCE_POINTER_ACTION,
} from "../market-overview";
import { qk } from "@/lib/queryKeys";
import type {
  MarketContext,
  TrackRecord,
  TrackRecordBreakdown,
  TrackedEvidenceSummaryResponse,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Pure visibility contract
// ---------------------------------------------------------------------------

describe("showEvidenceReviewerPointer — clean-clone visibility rule (M1)", () => {
  const cleanClone = {
    allLoaded: true,
    hasError: false,
    archiveTotal: 0,
    hasTrackedEvidence: true,
  };

  it("is visible in the real clean-clone state: empty archive + tracked evidence", () => {
    expect(showEvidenceReviewerPointer(cleanClone)).toBe(true);
  });

  it("hides while any channel is still loading (might have data)", () => {
    expect(showEvidenceReviewerPointer({ ...cleanClone, allLoaded: false })).toBe(false);
  });

  it("hides when a top-level query failed (banner owns that state)", () => {
    expect(showEvidenceReviewerPointer({ ...cleanClone, hasError: true })).toBe(false);
  });

  it("hides once the local archive has rows", () => {
    expect(showEvidenceReviewerPointer({ ...cleanClone, archiveTotal: 3 })).toBe(false);
  });

  it("hides without tracked evidence — that state belongs to the cold-start panel", () => {
    expect(
      showEvidenceReviewerPointer({ ...cleanClone, hasTrackedEvidence: false }),
    ).toBe(false);
  });

  it("treats an unknown archive total as not-proven-empty", () => {
    expect(showEvidenceReviewerPointer({ ...cleanClone, archiveTotal: null })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Copy contract — a published descriptive research record, not live data.
// ---------------------------------------------------------------------------

describe("evidence pointer copy (M1)", () => {
  const blob = `${EVIDENCE_POINTER_NOTE} ${EVIDENCE_POINTER_ACTION}`.toLowerCase();

  it("names the destination a published evidence record", () => {
    expect(EVIDENCE_POINTER_ACTION).toBe("Review the published evidence record");
    expect(blob).toContain("published evidence record");
  });

  it("distinguishes the published record from live archive data", () => {
    expect(blob).toContain("descriptive research record");
    expect(blob).toContain("not live");
  });

  it("carries no results / signals / opportunities / validated-strategy framing", () => {
    for (const w of ["results", "signals", "opportunities", "validated strategy", "trading"]) {
      expect(blob, `banned phrase "${w}"`).not.toContain(w);
    }
  });
});

// ---------------------------------------------------------------------------
// Seeded render smokes
// ---------------------------------------------------------------------------

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity },
    },
  });
}

const EMPTY_CONTEXT = {
  stress: null,
  regime_vector: null,
  snapshots: null,
  snapshots_meta: { stale: 0, unavailable: 0, total: 0 },
  context_explanations: {},
} as unknown as MarketContext;

const EMPTY_TRACK_RECORD = {
  total: 0,
  validated: 0,
  contradicted: 0,
  unresolved: 0,
  avg_support_ratio: null,
  revisit_scored: 0,
  rated_good: 0,
  rated_mixed: 0,
  rated_poor: 0,
} as TrackRecord;

const EMPTY_BREAKDOWN = {
  total_events: 0,
  by_mechanism_family: [],
  by_regime: [],
  by_compound_regime: [],
} as unknown as TrackRecordBreakdown;

function trackedEvidence(phase1: number, phase2: number): TrackedEvidenceSummaryResponse {
  return {
    ok: true,
    section: "tracked_evidence",
    schema_version: "v1",
    summary: {
      phase1_count: phase1,
      phase2_count: phase2,
      phase2_pass_count: 0,
      phase2_fail_count: 0,
      deferred_count: null,
    },
    phase1: [],
    phase2: [],
    fdr_scope_note: "Phase 1 and Phase 2 are separate pools.",
    limitations: [],
    warnings: [],
    errors: [],
  } as unknown as TrackedEvidenceSummaryResponse;
}

function seededRender(opts: {
  archiveTotal: number;
  phase1: number;
  phase2: number;
  onOpenEvidence?: () => void;
}): string {
  const client = testQueryClient();
  client.setQueryData(qk.marketContext(), EMPTY_CONTEXT);
  client.setQueryData(["market-overview-archive-events", 50], {
    total: opts.archiveTotal,
    items: [],
  });
  client.setQueryData(["market-overview-track-record-breakdown"], EMPTY_BREAKDOWN);
  client.setQueryData(qk.trackRecord(), EMPTY_TRACK_RECORD);
  client.setQueryData(
    qk.trackedEvidenceSummary(),
    trackedEvidence(opts.phase1, opts.phase2),
  );
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MarketOverview onOpenEvidence={opts.onOpenEvidence} />
    </QueryClientProvider>,
  );
}

function count(html: string, needle: string): number {
  return html.split(needle).length - 1;
}

describe("MarketOverview — reviewer pointer in the real clean-clone state (M1)", () => {
  it("renders the pointer exactly once with the reviewer action", () => {
    const html = seededRender({
      archiveTotal: 0,
      phase1: 5,
      phase2: 5,
      onOpenEvidence: () => {},
    });
    expect(count(html, EVIDENCE_POINTER_ACTION)).toBe(1);
    // tracked evidence present suppresses the true cold-start panel — the
    // two states stay distinguished, so the action can never render twice.
    expect(html).not.toContain("No archive");
  });

  it("does not render the pointer when the archive has rows", () => {
    const html = seededRender({
      archiveTotal: 12,
      phase1: 5,
      phase2: 5,
      onOpenEvidence: () => {},
    });
    expect(count(html, EVIDENCE_POINTER_ACTION)).toBe(0);
  });

  it("does not render the pointer in the true cold-start state (no tracked evidence)", () => {
    const html = seededRender({
      archiveTotal: 0,
      phase1: 0,
      phase2: 0,
      onOpenEvidence: () => {},
    });
    expect(count(html, EVIDENCE_POINTER_ACTION)).toBe(0);
    // the existing cold-start panel owns this state
    expect(html).toContain("No archive");
  });

  it("renders no dead action when App does not wire the callback", () => {
    const html = seededRender({ archiveTotal: 0, phase1: 5, phase2: 5 });
    expect(count(html, EVIDENCE_POINTER_ACTION)).toBe(0);
  });
});
