/**
 * Render smoke for ``TrackedEvidenceCard``.
 *
 * The card is presentational only — no React Query, no network — so
 * each test renders it directly with a hand-built envelope and asserts
 * the resulting HTML.  Pattern mirrors
 * ``components/pages/__tests__/section-c-demo.test.tsx``: vitest with
 * ``react-dom/server.renderToStaticMarkup``, no jsdom, no setup file.
 *
 * Pinned behaviours:
 *
 *  - Happy path: the 5 / 5 / 3 / 2 / 3 baseline counts all render.
 *  - Phase 2 absent: phase2_count = 0 renders the "not declared in this
 *    snapshot" copy instead of the pass / fail breakdown.
 *  - Errors non-empty: the first error string surfaces in the card
 *    footer with the documented "Tracked evidence layer unavailable:"
 *    prefix.
 *  - Phase 1 and Phase 2 are presented as separate labelled blocks; no
 *    "combined" or "across phase" wording appears.
 *  - Conservative vocabulary: the rendered HTML carries none of the
 *    forbidden surface-words (buy / sell / signal / proof / alpha /
 *    prediction) anywhere across the happy path or the error path.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { TrackedEvidenceSummaryResponse } from "@/lib/api";
import {
  TRACKED_EVIDENCE_COPY,
  TrackedEvidenceCard,
} from "../tracked-evidence-card";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FDR_NOTE =
  "Phase 1 and Phase 2 are independent FDR scopes. Phase 1 q-values " +
  "are pinned within the five-row Phase 1 denominator and are not " +
  "recomputed when Phase 2 candidates are screened. Phase 2 q-values " +
  "come from Benjamini-Hochberg step-up within the closed Phase 2 " +
  "pool only. q-values from one phase must not be compared as if " +
  "drawn from the other.";

function _baselineEnvelope(): TrackedEvidenceSummaryResponse {
  return {
    ok:             true,
    section:        "tracked_evidence",
    schema_version: "v1",
    summary: {
      phase1_count:      5,
      phase2_count:      5,
      phase2_pass_count: 3,
      phase2_fail_count: 2,
      deferred_count:    3,
    },
    phase1: [
      {
        phase:            "phase1",
        candidate_id:     "phase1-whr-2025-04-02",
        primary_ticker:   "WHR",
        benchmark_ticker: "XLY",
        event_date:       "2025-04-02",
        mechanism_family: "consumer-durable-tariff-pass-through",
        raw_p:            0.013514,
        q_bh:             0.013514,
        passes_bh_at_005: true,
        status:           "freeze_ready_pending_operator_review",
        caveat:           "",
      },
    ],
    phase2: [
      {
        phase:            "phase2",
        candidate_id:     "phase2-ba-2024-01-05",
        primary_ticker:   "BA",
        benchmark_ticker: "XLY",
        event_date:       "2024-01-05",
        mechanism_family: "issuer-specific-shock",
        raw_p:            0.001,
        q_bh:             0.005,
        passes_bh_at_005: true,
        status:           "with_caveat",
        caveat:           "",
      },
    ],
    fdr_scope_note: FDR_NOTE,
    limitations:    [],
    warnings:       [],
    errors:         [],
  };
}

function _envelopeWithoutPhase2(): TrackedEvidenceSummaryResponse {
  return {
    ...(_baselineEnvelope()),
    summary: {
      phase1_count:      5,
      phase2_count:      0,
      phase2_pass_count: 0,
      phase2_fail_count: 0,
      deferred_count:    3,
    },
    phase2: [],
  };
}

function _envelopeWithError(): TrackedEvidenceSummaryResponse {
  return {
    ...(_baselineEnvelope()),
    ok:     false,
    errors: ["Phase 1 freeze artifact not found at the expected path"],
  };
}

function renderCard(data: TrackedEvidenceSummaryResponse | null | undefined): string {
  return renderToStaticMarkup(<TrackedEvidenceCard data={data} />);
}

// ---------------------------------------------------------------------------
// Happy path — 5 / 5 / 3 / 2 / 3 baseline
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — happy path", () => {
  it("renders the section title and the eyebrow", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.sectionTitle);
    expect(html).toContain(TRACKED_EVIDENCE_COPY.sectionEyebrow);
  });

  it("renders Phase 1 freeze cohort count as 5", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase1Label);
    // The Phase 1 count column renders the literal "5" in a tabular
    // headline span; checking the substring is sufficient because
    // every count in the card is integer-formatted.
    expect(html).toContain(">5<");
  });

  it("renders Phase 2 BH/FDR pool count as 5 with pass=3 / fail=2", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase2Label);
    expect(html).toContain(">5<");
    expect(html).toContain(">3<");
    expect(html).toContain(">2<");
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase2PassLabel);
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase2FailLabel);
  });

  it("renders deferred methodology lessons count as 3", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.deferredLabel);
    expect(html).toContain(">3<");
  });

  it("renders the verbatim FDR scope note from the envelope", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(
      "Phase 1 and Phase 2 are independent FDR scopes",
    );
    expect(html).toContain(
      "q-values from one phase must not be compared",
    );
  });

  it("renders methodology and phase-history labels", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.methodologyLabel);
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phaseHistoryLabel);
  });

  it("renders muted repo-path captions, not clickable external links", () => {
    const html = renderCard(_baselineEnvelope());
    // Both repo-relative paths must appear verbatim — the path is the
    // affordance, the operator opens the file inside the repo.
    expect(html).toContain(
      "demo_artifacts/section_c_v2/phase_evidence_methodology.md",
    );
    expect(html).toContain("demo_artifacts/section_c_v2/phase_history.md");
    // The placeholder GitHub host that an earlier draft used must
    // not appear anywhere in the rendered output.
    expect(html).not.toContain("github.com/anthropics/claude-code");
    // No anchor element should be emitted for these references — the
    // brief is explicit that there is no public host to point at yet.
    expect(html).not.toContain("<a ");
    expect(html).not.toContain("href=");
  });

  it("does NOT render a Phase 2 absent line on the happy path", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.phase2AbsentLine);
  });

  it("does NOT render the error prefix on the happy path", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.errorPrefix);
  });
});

// ---------------------------------------------------------------------------
// Phase 2 absent / zero
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — Phase 2 absent", () => {
  it("renders the 'Phase 2 pool not declared' copy when phase2_count is 0", () => {
    const html = renderCard(_envelopeWithoutPhase2());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase2AbsentLine);
  });

  it("does NOT render the pass / fail breakdown rows when Phase 2 is absent", () => {
    const html = renderCard(_envelopeWithoutPhase2());
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.phase2PassLabel);
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.phase2FailLabel);
  });

  it("still renders the Phase 1 row at its real count", () => {
    const html = renderCard(_envelopeWithoutPhase2());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase1Label);
    expect(html).toContain(">5<");
  });

  it("still renders the scope note even when Phase 2 is absent", () => {
    const html = renderCard(_envelopeWithoutPhase2());
    expect(html).toContain(
      "Phase 1 and Phase 2 are independent FDR scopes",
    );
  });
});

// ---------------------------------------------------------------------------
// Errors non-empty
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — errors non-empty", () => {
  it("renders the first error string under the documented prefix", () => {
    const html = renderCard(_envelopeWithError());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.errorPrefix);
    expect(html).toContain(
      "Phase 1 freeze artifact not found at the expected path",
    );
  });

  it("still renders the per-phase columns when an error is present", () => {
    // The error footer is additive — the card never blanks out the
    // counts the envelope still carries.  This keeps a partial
    // degradation legible instead of going dark.
    const html = renderCard(_envelopeWithError());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase1Label);
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase2Label);
  });
});

// ---------------------------------------------------------------------------
// FDR scope separation — Phase 1 and Phase 2 are surfaced as separate
// labelled blocks; the card never invents a combined denominator or a
// cross-phase ranking.
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — FDR scope separation", () => {
  it("renders Phase 1 and Phase 2 as separate labelled blocks", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain("Phase 1 freeze cohort");
    expect(html).toContain("Phase 2 BH/FDR pool");
  });

  it("does NOT introduce a combined / cross-phase wording", () => {
    const html = renderCard(_baselineEnvelope()).toLowerCase();
    // Conservative greps: any of these would suggest the card is
    // smashing the two scopes together.  None should appear.
    expect(html).not.toContain("combined denominator");
    expect(html).not.toContain("combined q-value");
    expect(html).not.toContain("across phase");
    expect(html).not.toContain("cross-phase");
  });
});

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — loading state", () => {
  it("renders a skeleton (no heading, no eyebrow) when data is undefined", () => {
    const html = renderToStaticMarkup(
      <TrackedEvidenceCard data={undefined} />,
    );
    // The Skeleton primitive renders the section wrapper for layout +
    // an aria-label so a screen reader still hears "Tracked evidence
    // layer", but the body — visible heading + eyebrow + counts — is
    // not yet present.  Pinning the absence of the visible heading tag
    // and the body-only eyebrow text is enough to prove the loading
    // branch fired.
    expect(html).not.toContain("<h2");
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.sectionEyebrow);
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.phase1Label);
  });

  it("renders a skeleton when isLoading is true even with data", () => {
    const html = renderToStaticMarkup(
      <TrackedEvidenceCard data={_baselineEnvelope()} isLoading={true} />,
    );
    expect(html).not.toContain("<h2");
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.sectionEyebrow);
    expect(html).not.toContain(TRACKED_EVIDENCE_COPY.phase1Label);
  });
});

// ---------------------------------------------------------------------------
// Conservative vocabulary — the rendered HTML must not carry any of the
// banned surface-words across any of the three render paths.
// ---------------------------------------------------------------------------

const _FORBIDDEN_WORDS = [
  "buy",
  "sell",
  "signal",
  "proof",
  "alpha",
  "prediction",
] as const;

describe("TrackedEvidenceCard — conservative vocabulary", () => {
  it("renders no forbidden surface-words on the happy path", () => {
    const html = renderCard(_baselineEnvelope()).toLowerCase();
    for (const w of _FORBIDDEN_WORDS) {
      expect(
        html,
        `forbidden surface-word "${w}" leaked into the rendered card`,
      ).not.toContain(w);
    }
  });

  it("renders no forbidden surface-words on the Phase 2 absent path", () => {
    const html = renderCard(_envelopeWithoutPhase2()).toLowerCase();
    for (const w of _FORBIDDEN_WORDS) {
      expect(html).not.toContain(w);
    }
  });

  it("renders no forbidden surface-words on the error path", () => {
    const html = renderCard(_envelopeWithError()).toLowerCase();
    for (const w of _FORBIDDEN_WORDS) {
      expect(html).not.toContain(w);
    }
  });
});
