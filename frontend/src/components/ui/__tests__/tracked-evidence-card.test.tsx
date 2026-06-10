/**
 * Render smoke for ``TrackedEvidenceCard``.
 *
 * The card is presentational only — no React Query, no network — so
 * each test renders it directly with a hand-built envelope and asserts
 * the resulting HTML.  Pattern mirrors
 * ``components/pages/__tests__/section-c-demo.test.tsx``: vitest with
 * ``react-dom/server.renderToStaticMarkup``, no jsdom, no setup file.
 *
 * Hardened for Q1 M4 + L8 (test-only — no production change):
 *
 *  - M4: the baseline fixture now uses DISTINCT counts (7 / 5 / 3 / 2 / 4)
 *    and per-phase assertions are SCOPED to each phase's own block, so a
 *    Phase 1 / Phase 2 swap, drop, or duplicate is observable.  The old
 *    fixture used phase1 == phase2 == 5 with a global ``toContain(">5<")``,
 *    under which a swap was invisible — that weakness is documented below.
 *  - L8: banned-word checks match on VISIBLE TEXT (tags stripped) with
 *    word boundaries, so "seller" / "shortage" / "belong" / "alphabet" no
 *    longer false-match while the real words / phrases still do.
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
      // DISTINCT counts (Q1 M4): every count is a different integer so a
      // per-phase assertion can prove the right number lands in the right
      // block.  Markers: phase1 = ">7<", phase2 = ">5<", pass = ">3<",
      // fail = ">2<", deferred = ">4<".
      phase1_count:      7,
      phase2_count:      5,
      phase2_pass_count: 3,
      phase2_fail_count: 2,
      deferred_count:    4,
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

function _envelopeCounts(c: {
  phase1: number;
  phase2: number;
  pass: number;
  fail: number;
  deferred: number;
}): TrackedEvidenceSummaryResponse {
  return {
    ...(_baselineEnvelope()),
    summary: {
      phase1_count:      c.phase1,
      phase2_count:      c.phase2,
      phase2_pass_count: c.pass,
      phase2_fail_count: c.fail,
      deferred_count:    c.deferred,
    },
  };
}

function _envelopeWithoutPhase2(): TrackedEvidenceSummaryResponse {
  return {
    ...(_baselineEnvelope()),
    summary: {
      phase1_count:      7,
      phase2_count:      0,
      phase2_pass_count: 0,
      phase2_fail_count: 0,
      deferred_count:    4,
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
// Per-phase block extraction — slice the rendered HTML between the two phase
// eyebrows so a count is pinned to its OWN block.  This is what makes a Phase
// 1 / Phase 2 swap / drop / duplicate observable (Q1 M4).  The phase labels
// are unique to their eyebrows (the verbatim scope note says "Phase 1" /
// "Phase 2" but never the full "Phase 1 freeze cohort" / "Phase 2 BH/FDR
// pool" eyebrow strings), and ``deferredLabel`` follows both columns.
// ---------------------------------------------------------------------------

function _phase1Block(html: string): string {
  const i = html.indexOf(TRACKED_EVIDENCE_COPY.phase1Label);
  const j = html.indexOf(TRACKED_EVIDENCE_COPY.phase2Label, i + 1);
  return i < 0 || j < 0 ? "" : html.slice(i, j);
}

function _phase2Block(html: string): string {
  const i = html.indexOf(TRACKED_EVIDENCE_COPY.phase2Label);
  const j = html.indexOf(TRACKED_EVIDENCE_COPY.deferredLabel, i + 1);
  return i < 0 ? "" : html.slice(i, j < 0 ? html.length : j);
}

// ---------------------------------------------------------------------------
// Banned-word matcher (Q1 L8) — visible text, word boundaries.  Tags are
// stripped so a banned substring in a class/attribute is never matched, and
// ``\b`` boundaries avoid false positives ("seller" / "shortage" / "belong"
// / "alphabet") while still catching the real words and the "live trading"
// phrase (with an optional space/hyphen).
// ---------------------------------------------------------------------------

const _BANNED_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = [
  ["buy", /\bbuy\b/],
  ["sell", /\bsell\b/],
  ["long", /\blong\b/],
  ["short", /\bshort\b/],
  ["alpha", /\balpha\b/],
  ["signal", /\bsignal\b/],
  ["proof", /\bproof\b/],
  ["proves", /\bproves\b/],
  ["prediction", /\bprediction\b/],
  ["live trading", /\blive[\s-]?trading\b/],
];

function _visibleText(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").toLowerCase();
}

function _bannedWordsIn(text: string): string[] {
  return _BANNED_PATTERNS.filter(([, re]) => re.test(text)).map(([w]) => w);
}

// ---------------------------------------------------------------------------
// Happy path — 7 / 5 / 3 / 2 / 4 baseline (distinct counts)
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — happy path", () => {
  it("renders the section title and the eyebrow", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.sectionTitle);
    expect(html).toContain(TRACKED_EVIDENCE_COPY.sectionEyebrow);
  });

  it("renders the Phase 1 freeze-cohort count in the Phase 1 block (7, not Phase 2's 5)", () => {
    const p1 = _phase1Block(renderCard(_baselineEnvelope()));
    expect(p1).toContain(TRACKED_EVIDENCE_COPY.phase1Label);
    expect(p1).toContain(">7<");
    expect(p1).not.toContain(">5<"); // Phase 2's count must NOT leak into Phase 1
  });

  it("renders the Phase 2 BH/FDR count + pass/fail in the Phase 2 block (5/3/2, not Phase 1's 7)", () => {
    const p2 = _phase2Block(renderCard(_baselineEnvelope()));
    expect(p2).toContain(TRACKED_EVIDENCE_COPY.phase2Label);
    expect(p2).toContain(">5<");
    expect(p2).toContain(">3<");
    expect(p2).toContain(">2<");
    expect(p2).not.toContain(">7<"); // Phase 1's count must NOT leak into Phase 2
    expect(p2).toContain(TRACKED_EVIDENCE_COPY.phase2PassLabel);
    expect(p2).toContain(TRACKED_EVIDENCE_COPY.phase2FailLabel);
  });

  it("renders deferred methodology lessons count as 4", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.deferredLabel);
    expect(html).toContain(">4<");
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
    expect(html).toContain(
      "evidence_artifacts/section_c_v2/phase_evidence_methodology.md",
    );
    expect(html).toContain("evidence_artifacts/section_c_v2/phase_history.md");
    expect(html).not.toContain("github.com/anthropics/claude-code");
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
// M4 — phase-count discrimination.  The old test used equal counts + a global
// substring check, so a Phase 1 / Phase 2 swap was invisible.  These tests
// document that weakness and prove the scoped assertions now catch it.
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — phase-count discrimination (Q1 M4)", () => {
  it("documents why equal Phase 1 / Phase 2 counts hid swaps", () => {
    // With phase1 == phase2 == 5 (the OLD fixture) the SAME ">5<" marker
    // appears in both blocks, so swapping the two columns changes nothing
    // observable — a global ``toContain(">5<")`` (or even a scoped check)
    // cannot tell them apart.  Distinct counts are what make it testable.
    const html = renderCard(_envelopeCounts({ phase1: 5, phase2: 5, pass: 3, fail: 2, deferred: 4 }));
    expect(_phase1Block(html)).toContain(">5<");
    expect(_phase2Block(html)).toContain(">5<");
  });

  it("scoped per-block assertions catch a swap the old substring check missed", () => {
    // A swap renders Phase 2's value in Phase 1's slot and vice-versa.
    const swapped = renderCard(_envelopeCounts({ phase1: 5, phase2: 7, pass: 3, fail: 2, deferred: 4 }));

    // OLD style (global substring): blind — both numbers still appear somewhere.
    expect(swapped).toContain(">5<");
    expect(swapped).toContain(">7<");

    // NEW style (scoped): the wrong number lands in each block → detected.
    expect(_phase1Block(swapped)).toContain(">5<");
    expect(_phase1Block(swapped)).not.toContain(">7<");
    expect(_phase2Block(swapped)).toContain(">7<");
    expect(_phase2Block(swapped)).not.toContain(">5<");
  });

  it("scoped assertions catch a dropped Phase 2 count (rendered as a dash)", () => {
    const dropped = _baselineEnvelope();
    // Simulate a drop: Phase 2 count goes missing while the pass/fail
    // breakdown still references the pool — the scoped check flags it.
    (dropped.summary as Record<string, unknown>).phase2_count = null;
    const p2 = _phase2Block(renderCard(dropped));
    expect(p2).not.toContain(">5<"); // the real count no longer renders
    expect(p2).toContain(">—<");      // it degrades to the em-dash placeholder
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

  it("still renders the Phase 1 row at its real count in the Phase 1 block", () => {
    const p1 = _phase1Block(renderCard(_envelopeWithoutPhase2()));
    expect(p1).toContain(TRACKED_EVIDENCE_COPY.phase1Label);
    expect(p1).toContain(">7<");
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
    const html = renderCard(_envelopeWithError());
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase1Label);
    expect(html).toContain(TRACKED_EVIDENCE_COPY.phase2Label);
  });
});

// ---------------------------------------------------------------------------
// FDR scope separation — Phase 1 and Phase 2 are surfaced as separate
// labelled blocks; the card never invents a combined denominator.
// ---------------------------------------------------------------------------

describe("TrackedEvidenceCard — FDR scope separation", () => {
  it("renders Phase 1 and Phase 2 as separate labelled blocks", () => {
    const html = renderCard(_baselineEnvelope());
    expect(html).toContain("Phase 1 freeze cohort");
    expect(html).toContain("Phase 2 BH/FDR pool");
  });

  it("does NOT introduce a combined / cross-phase wording", () => {
    const html = renderCard(_baselineEnvelope()).toLowerCase();
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
// L8 — banned-word matcher: word-boundary, not substring.
// ---------------------------------------------------------------------------

describe("banned-word matcher — word-boundary, not substring (Q1 L8)", () => {
  it("does NOT false-match innocuous words that merely contain a banned substring", () => {
    const innocuous =
      "the seller saw a shortage; we belong here. alphabet, alphanumeric. " +
      "signalling, shortfall, buyer, proofread, prolonged, predictions-page.";
    expect(_bannedWordsIn(innocuous)).toEqual([]);
  });

  it("still catches the real banned words and phrases", () => {
    const cases: Array<[string, string]> = [
      ["buy now", "buy"],
      ["sell side", "sell"],
      ["go long here", "long"],
      ["short the name", "short"],
      ["find alpha", "alpha"],
      ["a clear signal", "signal"],
      ["this is proof", "proof"],
      ["it proves the thesis", "proves"],
      ["a prediction", "prediction"],
      ["live trading desk", "live trading"],
      ["live-trading", "live trading"],
    ];
    for (const [text, expected] of cases) {
      expect(_bannedWordsIn(text)).toContain(expected);
    }
  });
});

describe("TrackedEvidenceCard — conservative vocabulary (visible text)", () => {
  it("renders no banned words on the happy path", () => {
    expect(_bannedWordsIn(_visibleText(renderCard(_baselineEnvelope())))).toEqual([]);
  });

  it("renders no banned words on the Phase 2 absent path", () => {
    expect(_bannedWordsIn(_visibleText(renderCard(_envelopeWithoutPhase2())))).toEqual([]);
  });

  it("renders no banned words on the error path", () => {
    expect(_bannedWordsIn(_visibleText(renderCard(_envelopeWithError())))).toEqual([]);
  });
});
