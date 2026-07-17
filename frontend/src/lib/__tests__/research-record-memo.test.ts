/**
 * M2/N2 — canonical research-record memo builder
 * (second-order-research-record-v2).
 *
 * The builder is a pure function: canonical static evidence constants are
 * imported (never retyped), the Mission G / Mission I / Mission J contract
 * payloads are passed in as explicit lanes, and the output is deterministic
 * LF Markdown.  N2 bumped the schema to v2: the memo is exactly 13 sections
 * with the Mission I ordinary-period comparison ledger between Mission G
 * and Mission J.  These tests pin the memo contract:
 *   - byte-identical output for identical input (incl. a reviewed golden);
 *   - every mandatory section present, in order, never silently omitted;
 *   - denominators equal the canonical constants (no retyped number);
 *   - both accepted outcome ledgers stay separate with the do-not-merge
 *     warning, and no blended / composite result exists;
 *   - Mission G / I / J wording comes from the contract payload (sentinel
 *     mutation proves no hand-copied frozen conclusion);
 *   - unavailable lanes are explicit, ordinary / contradicted / mixed /
 *     unresolved states stay visible;
 *   - provenance renders or honestly says "not recorded";
 *   - no undefined / NaN / object-string leaks, no banned framing outside
 *     negated non-claim / claim-ceiling blocks;
 *   - download mechanics (separate helper, injected adapter): one blob URL,
 *     UTF-8 Markdown MIME, stable filename, anchor removed, URL revoked.
 */
import { describe, expect, it } from "vitest";

import {
  buildResearchRecordMemo,
  downloadResearchRecordMemo,
  researchRecordExportReady,
  researchRecordMemoInput,
  RESEARCH_RECORD_FILENAME,
  RESEARCH_RECORD_MIME_TYPE,
  RESEARCH_RECORD_SCHEMA_VERSION,
  type MemoDownloadAdapter,
  type MemoDownloadAnchor,
  type ResearchRecordMemoInput,
} from "../research-record-memo";
import {
  ACCEPTED_CORPUS as AC,
  DENOMINATOR_LEDGER,
  FAMILY_COVERAGE as FC,
} from "../accepted-corpus";
import { RESEARCH_FINDINGS as F } from "../research-findings";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "../effective-independent-evidence";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "../mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "../representative-case-library";
import { missionJFixture } from "@/components/ui/__tests__/mission-j-fixture";
import { missionIFixture } from "@/components/ui/__tests__/mission-i-fixture";
import {
  missionGFixture,
  MISSION_G_APPROVED_OPEC_WORDING,
} from "@/components/ui/__tests__/mission-g-fixture";
import { GOLDEN_RESEARCH_RECORD_ALL_UNAVAILABLE } from "./research-record-golden";

// ---------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------

function completeInput(): ResearchRecordMemoInput {
  return {
    missionG: { available: true, data: missionGFixture() },
    missionI: { available: true, data: missionIFixture() },
    missionJ: { available: true, data: missionJFixture() },
  };
}

function gUnavailableInput(): ResearchRecordMemoInput {
  return {
    missionG: { available: false },
    missionI: { available: true, data: missionIFixture() },
    missionJ: { available: true, data: missionJFixture() },
  };
}

function iUnavailableInput(): ResearchRecordMemoInput {
  return {
    missionG: { available: true, data: missionGFixture() },
    missionI: { available: false },
    missionJ: { available: true, data: missionJFixture() },
  };
}

function jUnavailableInput(): ResearchRecordMemoInput {
  return {
    missionG: { available: true, data: missionGFixture() },
    missionI: { available: true, data: missionIFixture() },
    missionJ: { available: false },
  };
}

function allUnavailableInput(): ResearchRecordMemoInput {
  return {
    missionG: { available: false },
    missionI: { available: false },
    missionJ: { available: false },
  };
}

const complete = buildResearchRecordMemo(completeInput());
const gUnavailable = buildResearchRecordMemo(gUnavailableInput());
const iUnavailable = buildResearchRecordMemo(iUnavailableInput());
const jUnavailable = buildResearchRecordMemo(jUnavailableInput());
const allUnavailable = buildResearchRecordMemo(allUnavailableInput());
const allVariants: Array<[string, string]> = [
  ["complete", complete],
  ["mission G unavailable", gUnavailable],
  ["mission I unavailable", iUnavailable],
  ["mission J unavailable", jUnavailable],
  ["all unavailable", allUnavailable],
];

const SECTION_HEADINGS = [
  "## 1. Record identity",
  "## 2. Purpose and permanent claim ceiling",
  "## 3. Canonical denominator ledger",
  "## 4. Accepted outcome ledgers",
  "## 5. Independence caution",
  "## 6. Mission G — separate historical ledger",
  "## 7. Mission I — ordinary-period comparison ledger",
  "## 8. Mission J — separate robustness and transmission ledger",
  "## 9. Mechanism-family evidence inventory",
  "## 10. Representative-case context",
  "## 11. Data limitations and unresolved states",
  "## 12. Provenance and reproduction appendix",
  "## 13. Final non-claims",
];

// ---------------------------------------------------------------------------
// 1. Determinism and formatting
// ---------------------------------------------------------------------------

describe("research-record memo — determinism and formatting", () => {
  it("returns byte-identical output for independently constructed equal input", () => {
    expect(buildResearchRecordMemo(completeInput())).toBe(
      buildResearchRecordMemo(completeInput()),
    );
    expect(buildResearchRecordMemo(allUnavailableInput())).toBe(
      buildResearchRecordMemo(allUnavailableInput()),
    );
    const stamped: ResearchRecordMemoInput = {
      ...completeInput(),
      exportedAt: "2026-07-16T12:00:00Z",
    };
    expect(buildResearchRecordMemo(stamped)).toBe(
      buildResearchRecordMemo({ ...completeInput(), exportedAt: "2026-07-16T12:00:00Z" }),
    );
  });

  it("uses LF line endings only and ends with a single trailing newline", () => {
    for (const [name, memo] of allVariants) {
      expect(memo, name).not.toContain("\r");
      expect(memo.endsWith("\n"), name).toBe(true);
      expect(memo.endsWith("\n\n"), name).toBe(false);
    }
  });

  it("emits no trailing whitespace on any line", () => {
    for (const [name, memo] of allVariants) {
      for (const line of memo.split("\n")) {
        expect(line, `${name}: ${JSON.stringify(line)}`).not.toMatch(/[ \t]+$/);
      }
    }
  });

  it("matches the reviewed golden fixture byte-for-byte (all three lanes unavailable)", () => {
    expect(allUnavailable).toBe(GOLDEN_RESEARCH_RECORD_ALL_UNAVAILABLE);
  });

  it("carries the v2 schema version exactly once — the section contract changed with it", () => {
    for (const [name, memo] of allVariants) {
      expect(memo.split(RESEARCH_RECORD_SCHEMA_VERSION).length - 1, name).toBe(1);
    }
    expect(RESEARCH_RECORD_SCHEMA_VERSION).toBe("second-order-research-record-v2");
    // the retired v1 identifier must not linger anywhere in the output
    for (const [name, memo] of allVariants) {
      expect(memo, name).not.toContain("second-order-research-record-v1");
    }
  });

  it("renders every mandatory section heading in order, in every variant", () => {
    for (const [name, memo] of allVariants) {
      let last = -1;
      for (const heading of SECTION_HEADINGS) {
        const idx = memo.indexOf(`\n${heading}\n`);
        expect(idx, `${name}: ${heading}`).toBeGreaterThan(last);
        last = idx;
      }
    }
  });

  it("labels a supplied export timestamp as export metadata, and omits the line otherwise", () => {
    const stamped = buildResearchRecordMemo({
      ...completeInput(),
      exportedAt: "2026-07-16T12:00:00Z",
    });
    expect(stamped).toContain(
      "- Export timestamp (export metadata only, not a research computation date): 2026-07-16T12:00:00Z",
    );
    expect(complete).not.toContain("Export timestamp");
  });

  it("never leaks undefined, object strings, or NaN", () => {
    for (const [name, memo] of allVariants) {
      expect(memo, name).not.toContain("undefined");
      expect(memo, name).not.toContain("[object Object]");
      expect(memo, name).not.toContain("NaN");
    }
  });
});

// ---------------------------------------------------------------------------
// 2. Mandatory claim ceiling and non-claims (cannot be hidden by missing data)
// ---------------------------------------------------------------------------

describe("research-record memo — mandatory non-claims", () => {
  it("renders the permanent claim ceiling in every variant", () => {
    for (const [name, memo] of allVariants) {
      expect(memo, name).toContain("- not a recommendation;");
      expect(memo, name).toContain("- not a prediction surface;");
      expect(memo, name).toContain("- not evidence of alpha or tradeability;");
      expect(memo, name).toContain("- not a claim of causality;");
      expect(memo, name).toContain("- not a claim of single-event statistical significance.");
    }
  });

  it("ends with the exact bounded final non-claims block in every variant", () => {
    const finalBlock =
      "This record does not establish causality, statistical significance,\n" +
      "predictive performance, alpha, tradeability, or an investment recommendation.\n";
    for (const [name, memo] of allVariants) {
      expect(memo.endsWith(finalBlock), name).toBe(true);
    }
  });

  it("renders every standing project non-claim in the final section", () => {
    for (const line of F.nonClaims) {
      expect(complete).toContain(`- ${line}`);
    }
  });
});

// ---------------------------------------------------------------------------
// 3. Canonical denominators — values equal the canonical inputs
// ---------------------------------------------------------------------------

describe("research-record memo — canonical denominator ledger", () => {
  it("shares the exact ledger rows composed from the canonical constants", () => {
    // The shared ledger itself must be composed, not retyped.
    expect(DENOMINATOR_LEDGER.map((r) => r.value)).toEqual([
      String(AC.savedEvents),
      String(AC.coverageDenominator),
      String(AC.trackRecordTotal),
      `${AC.eventStudyAvailable} / ${AC.coverageDenominator}`,
      String(FC.stagedCandidates),
    ]);
  });

  it("renders every ledger row with its value, label, and semantic note", () => {
    DENOMINATOR_LEDGER.forEach((row, i) => {
      expect(complete).toContain(
        `| ${i + 1} | ${row.value} | ${row.label} | ${row.note} |`,
      );
    });
    expect(complete).toContain(
      `Current accepted-lens snapshot as of ${AC.restatedOn}.`,
    );
  });
});

// ---------------------------------------------------------------------------
// 4. Accepted outcome ledgers — separate, never merged
// ---------------------------------------------------------------------------

describe("research-record memo — accepted outcome ledgers", () => {
  it("renders both ledgers separately with their canonical rule names and splits", () => {
    expect(complete).toContain("### Any-support / OR-rule ledger");
    expect(complete).toContain("### Directional-majority ledger");
    expect(complete).toContain(`- Rule: ${AC.orRuleName} (db.compute_track_record)`);
    expect(complete).toContain(`- Rule: ${AC.directionalMajority.ruleName}`);
    expect(complete).toContain(
      `- Split: ${AC.anySupporting} any-supporting / ${AC.contradicted} contradicted / ${AC.unresolved} unresolved`,
    );
    expect(complete).toContain(
      `- Split: ${AC.directionalMajority.validated} validated / ${AC.directionalMajority.contradicted} contradicted / ${AC.directionalMajority.unresolved} unresolved`,
    );
    expect(complete).toContain(
      `- Tie / unresolved handling: ${AC.directionalMajority.tieNote}`,
    );
    expect(complete).toContain(
      `Why the two distributions differ: ${AC.lensDivergenceNote}`,
    );
  });

  it("carries the explicit do-not-merge warning and computes no blended result", () => {
    expect(complete).toContain("Do not merge these two ledgers.");
    for (const [name, memo] of allVariants) {
      expect(memo.toLowerCase(), name).not.toMatch(/\bcomposite score\b/);
      expect(memo.toLowerCase(), name).not.toMatch(/\bblended\b/);
      // 86 + 97 pooled sample must never appear
      expect(memo, name).not.toContain("183");
    }
  });

  it("keeps the ordinary / mixed baseline characterization visible with its snapshot date", () => {
    expect(complete).toContain(`as of ${F.asOf}, superseded denominators`);
    expect(complete).toContain(`verdict ${F.t2aBaseline.verdict}`);
    expect(complete).toContain(F.t3aMulti.verdict);
    expect(complete).toContain(F.t2bPrimary.reliability);
    expect(complete).toContain(F.t4aCoverage.limitation);
    expect(complete).toContain(
      `${F.corpus.marketScored} market-scored / ${F.corpus.anySupporting} any-supporting / ${F.corpus.contradicted} contradicted / ${F.corpus.unresolved} unresolved`,
    );
  });
});

// ---------------------------------------------------------------------------
// 5. Independence caution
// ---------------------------------------------------------------------------

describe("research-record memo — independence caution", () => {
  it("renders the canonical effective-independent-evidence readout", () => {
    expect(complete).toContain(
      `The ${EIE.acceptedTrackRecordRows} accepted track-record rows group into ${EIE.clusterCount} descriptive market-story clusters`,
    );
    expect(complete).toContain(
      `The largest cluster holds ${EIE.largestClusterRows} rows and ${EIE.representativeCasesInLargest} / ${EIE.representativeCasesTotal} representative cases.`,
    );
    expect(complete).toContain("not an inferential effective sample size");
    expect(complete).toContain(`not ${EIE.acceptedTrackRecordRows} separate market stories`);
  });
});

// ---------------------------------------------------------------------------
// 6 + 7. Mission lanes — never omitted, explicit when unavailable, wording
// from the contract payload only
// ---------------------------------------------------------------------------

describe("research-record memo — Mission G lane", () => {
  it("is never silently omitted", () => {
    for (const [name, memo] of allVariants) {
      expect(memo, name).toContain("## 6. Mission G — separate historical ledger");
    }
  });

  it("states the unavailable lane explicitly", () => {
    expect(gUnavailable).toContain("Mission G research record: unavailable");
    expect(allUnavailable).toContain("Mission G research record: unavailable");
    expect(complete).not.toContain("Mission G research record: unavailable");
  });

  it("renders the contract fields verbatim when available", () => {
    const g = missionGFixture();
    expect(complete).toContain(g.lanes.pooling_prohibition);
    expect(complete).toContain(g.main_result.headline);
    expect(complete).toContain(g.main_result.fomc_null.statement);
    expect(complete).toContain(MISSION_G_APPROVED_OPEC_WORDING);
    expect(complete).toContain(g.bounded_opec_association.confound_note);
    expect(complete).toContain(g.credit_limitation.note);
    expect(complete).toContain(g.failed_thesis_mechanism_comparability.statement);
    for (const nc of g.non_claims) expect(complete).toContain(`- ${nc}`);
    expect(complete).toContain(
      `Sign reversals under uniform stress: ${g.stability.loeo_sign_reversals}/${g.stability.continuous_associations} leave-one-event-out · ${g.stability.loyo_sign_reversals}/${g.stability.continuous_associations} leave-one-calendar-year-out.`,
    );
    expect(complete).toContain(g.source_artifacts.readout);
    expect(complete).toContain(g.source_artifacts.mechanism_attrition);
  });

  it("takes its wording from the payload, not from a hand-copied conclusion (sentinel)", () => {
    const g = missionGFixture();
    g.main_result.headline = "SENTINEL-G-HEADLINE";
    g.bounded_opec_association.wording = "SENTINEL-G-WORDING";
    const memo = buildResearchRecordMemo({
      missionG: { available: true, data: g },
      missionI: { available: false },
      missionJ: { available: false },
    });
    expect(memo).toContain("SENTINEL-G-HEADLINE");
    expect(memo).toContain("SENTINEL-G-WORDING");
    expect(memo).not.toContain(MISSION_G_APPROVED_OPEC_WORDING);
  });
});

describe("research-record memo — Mission I lane (N2)", () => {
  it("is never silently omitted, and sits between the G and J ledgers", () => {
    for (const [name, memo] of allVariants) {
      const g = memo.indexOf("## 6. Mission G — separate historical ledger");
      const i = memo.indexOf("## 7. Mission I — ordinary-period comparison ledger");
      const j = memo.indexOf("## 8. Mission J — separate robustness and transmission ledger");
      expect(g, name).toBeGreaterThan(-1);
      expect(i, name).toBeGreaterThan(g);
      expect(j, name).toBeGreaterThan(i);
    }
  });

  it("states the unavailable lane explicitly", () => {
    expect(iUnavailable).toContain("Mission I research record: unavailable");
    expect(allUnavailable).toContain("Mission I research record: unavailable");
    expect(complete).not.toContain("Mission I research record: unavailable");
  });

  it("renders the frozen question, separate denominators and reference Ns from the payload", () => {
    const i = missionIFixture();
    expect(complete).toContain(i.constitution.frozen_question);
    expect(complete).toContain("- FOMC: 65 event windows");
    expect(complete).toContain("- OPEC: 32 event windows");
    expect(complete).toContain(`${i.constitution.family_pooling_prohibition}.`);
    // eligible ordinary-reference denominators per family × horizon
    for (const lane of i.universe.families) {
      for (const h of lane.horizons) {
        expect(complete).toContain(
          `| ${lane.family} | ${h.horizon} | ${lane.study_event_n_available} | ${h.reference_n_available} | ${h.non_overlapping_reference_n} | ${h.status} |`,
        );
      }
    }
  });

  it("renders all 20 primary cells in frozen order with payload-exact values", () => {
    const i = missionIFixture();
    let last = -1;
    for (const cell of i.primary_cells) {
      const row = `| ${cell.cell} | ${cell.cell_key} | ${cell.event_n_available} | ${cell.reference_n_available} | ${cell.memp} | ${cell.signed_percentile_median} | ${cell.calibration_percentile} |`;
      const idx = complete.indexOf(row);
      expect(idx, cell.cell_key).toBeGreaterThan(last);
      last = idx;
    }
  });

  it("keeps the FOMC 20d structural unavailability explicit", () => {
    expect(complete).toContain("| FOMC | 20d | 65 | 0 | 0 | structurally_infeasible |");
    expect(complete).toContain("not a data gap");
  });

  it("renders the separate family readouts verbatim", () => {
    const i = missionIFixture();
    for (const r of i.family_horizon_readout) {
      expect(complete).toContain(`- ${r.family} ${r.horizon}: ${r.headline}`);
    }
  });

  it("renders all six falsifier families separately with the frozen results", () => {
    const i = missionIFixture();
    for (const key of ["f1", "f2", "f3", "f4", "f5", "f6"] as const) {
      expect(complete).toContain(i.falsifiers.definitions[key]);
    }
    expect(complete).toContain("0 / 20 primary-cell direction changes");
    expect(complete).toContain(i.falsifiers.f3_overlap_decimation.reading);
    expect(complete).toContain(i.falsifiers.f3_overlap_decimation.limitation);
    expect(complete).toContain("10 / 160");
    expect(complete).toContain("32 / 904");
    expect(complete).toContain("9 inside · 11 outside (8 upper · 3 lower)");
    // never compressed into a pass count or score
    expect(complete.toLowerCase()).not.toMatch(/\d\s*\/\s*6 (passed|failed)/);
    expect(complete.toLowerCase()).not.toContain("robustness score");
  });

  it("keeps the FOMC 5d raw knife-edge fragility visible", () => {
    const i = missionIFixture();
    expect(complete).toContain(i.fragility.knife_edge.cell_key);
    expect(complete).toContain("MEMP 0.501155");
    expect(complete).toContain("LOEO 32 / 65");
    expect(complete).toContain(i.fragility.knife_edge.explanation);
  });

  it("renders the conclusion, clarifier, limitations and non-claims verbatim", () => {
    const i = missionIFixture();
    expect(complete).toContain(`- Conclusion (verbatim): ${i.whole_mission_conclusion.statement}`);
    expect(complete).toContain(`- Clarifier (verbatim): ${i.whole_mission_conclusion.clarifier}`);
    for (const limit of i.unresolved_or_limits) {
      expect(complete).toContain(`- ${limit}`);
    }
    for (const nc of i.non_claims) {
      expect(complete).toContain(`- ${nc}`);
    }
  });

  it("takes its wording from the payload, not from a hand-copied conclusion (sentinel)", () => {
    const i = missionIFixture();
    i.whole_mission_conclusion.statement = "SENTINEL-I-CONCLUSION";
    i.family_horizon_readout[0].headline = "SENTINEL-I-HEADLINE";
    const memo = buildResearchRecordMemo({
      missionG: { available: false },
      missionI: { available: true, data: i },
      missionJ: { available: false },
    });
    expect(memo).toContain("SENTINEL-I-CONCLUSION");
    expect(memo).toContain("SENTINEL-I-HEADLINE");
    expect(memo).not.toContain("rejects the blanket idea");
    expect(memo).not.toContain(
      "broad, perturbation-stable elevation in one-day response magnitude",
    );
  });

  it("carries the Mission I provenance appendix — hashes, repro, honest nulls", () => {
    const i = missionIFixture();
    for (const src of Object.values(i.provenance.sources)) {
      expect(complete).toContain(
        `${src.artifact} — sha256 ${src.sha256} · ${src.bytes} bytes`,
      );
    }
    for (const cmd of i.provenance.reproduction.commands) {
      expect(complete).toContain(cmd);
    }
    expect(complete).toContain("- Computation dates: not recorded");
    expect(complete).toContain("- Execution commits: not recorded");
  });
});

describe("research-record memo — Mission J lane", () => {
  it("is never silently omitted", () => {
    for (const [name, memo] of allVariants) {
      expect(memo, name).toContain(
        "## 8. Mission J — separate robustness and transmission ledger",
      );
    }
  });

  it("states the unavailable lane explicitly", () => {
    expect(jUnavailable).toContain("Mission J research record: unavailable");
    expect(allUnavailable).toContain("Mission J research record: unavailable");
    expect(complete).not.toContain("Mission J research record: unavailable");
  });

  it("derives the frozen J1B / J2 / J3 states from the payload", () => {
    const j = missionJFixture();
    // 12/12 J1B cells ELEVATED — computed from the payload cells
    expect(complete).toContain(
      `${j.j1b.cells.filter((c) => c.node_state === "ELEVATED").length}/${j.j1b.cells.length} frozen cells at state ELEVATED`,
    );
    // all three panels at their published modifier
    for (const p of j.j1b.panels) {
      expect(complete).toContain(`primary ${p.primary}): ${p.modifier}`);
    }
    // J2 timing: lens-dependent split stays visible
    expect(complete).toContain("| raw_return | ORDINARY_UNRESOLVED |");
    expect(complete).toContain("| spy_relative_ar | ORDINARY_UNRESOLVED |");
    expect(complete).toContain("| sector_relative_ar | ELEVATED |");
    expect(complete).toContain("| sar | ELEVATED |");
    // C2 OPEC register tags 0/65; C1 unadjudicable at full weight
    expect(complete).toContain(
      `tags ${j.j2.collisions.c2.tagged_n} of ${j.j2.collisions.c2.of} events`,
    );
    expect(complete).toContain(`- C1 (${j.j2.collisions.c1.families}): ${j.j2.collisions.c1.status} — ${j.j2.collisions.c1.reason}`);
    // all three J3 edges PROPAGATED under the frozen rules
    for (const e of j.j3.edges) {
      expect(complete).toContain(`- ${e.edge} ${e.from} → ${e.to}: ${e.state}.`);
    }
    // measurement-limited rates path + same-sample Class B, verbatim
    expect(complete).toContain(j.j1b.measurement_limited.statement);
    expect(complete).toContain(
      "all of it is same-sample Class B evidence: post-outcome robustness under prospectively frozen new tests, never independent historical confirmation.",
    );
  });

  it("renders the frozen qualifiers, supports, unresolved and non-claims verbatim", () => {
    const j = missionJFixture();
    expect(complete).toContain(j.j3.timing_qualifier);
    expect(complete).toContain(j.j3.collision_qualifier);
    for (const s of j.j3.supports) expect(complete).toContain(`- ${s}`);
    for (const u of j.j3.unresolved) expect(complete).toContain(`- ${u}`);
    for (const nc of j.j3.non_claims) expect(complete).toContain(`- ${nc}`);
    for (const nc of j.j1b.non_claims) expect(complete).toContain(`- ${nc}`);
    expect(complete).toContain(j.provenance.publication_status);
    expect(complete).toContain(j.provenance.no_recompute_statement);
  });

  it("takes its wording from the payload, not from a hand-copied conclusion (sentinel)", () => {
    const j = missionJFixture();
    j.j3.timing_qualifier = "SENTINEL-J-TIMING";
    j.j3.supports = ["SENTINEL-J-SUPPORT"];
    const memo = buildResearchRecordMemo({
      missionG: { available: false },
      missionI: { available: false },
      missionJ: { available: true, data: j },
    });
    expect(memo).toContain("SENTINEL-J-TIMING");
    expect(memo).toContain("- SENTINEL-J-SUPPORT");
    // the replaced timing_qualifier's unique frozen sentence must be gone
    expect(memo).not.toContain(
      "The J0 section-15 withdrawal condition for the 1d concentration claim was not triggered",
    );
    expect(memo).not.toContain("mechanism-consistent descriptive pattern");
  });
});

// ---------------------------------------------------------------------------
// 8 + 9. Family inventory and representative cases
// ---------------------------------------------------------------------------

describe("research-record memo — family inventory and representative cases", () => {
  it("renders the E2 inventory rows and buckets from the canonical constants", () => {
    expect(complete).toContain(`- Lens: ${MFE.lens}`);
    expect(complete).toContain(
      `- Buckets: single-match ${MFE.buckets.singleMatch} · multi-match ${MFE.buckets.multiMatch} · unclassified ${MFE.buckets.unclassified} = ${MFE.buckets.sum}`,
    );
    for (const fam of MFE.families) {
      expect(complete).toContain(
        `| ${fam.family} | ${fam.n} | ${fam.s} / ${fam.c} / ${fam.u} | ${fam.esAvailable} / ${fam.esOf} |`,
      );
    }
  });

  it("renders all 15 representative cases with roles, outcomes, and caveats", () => {
    for (const c of RCL.cases) {
      expect(complete).toContain(
        `| #${c.id} | ${c.role} | ${c.family} | ${c.outcome} | ${c.eventStudy ? "yes" : "no"} |`,
      );
    }
    expect(complete).toContain(
      `${RCL.totals.total} illustrative cases across ${RCL.totals.familiesTotal} mechanism families`,
    );
    expect(complete).toContain(`selection frozen @ ${RCL.sourceCommit}`);
    expect(complete).toContain(`outcomes restated ${RCL.outcomesRestatedOn}`);
    // unresolved / contradicted cases stay listed — not a supportive-only slate
    expect(complete).toContain("| #29 | new | supply_shock | contradiction |");
    expect(complete).toContain("| #153 | new | sanction | unresolved | no |");
  });
});

// ---------------------------------------------------------------------------
// 10 + 11. Limitations and provenance
// ---------------------------------------------------------------------------

describe("research-record memo — limitations and provenance appendix", () => {
  it("keeps unavailable / unresolved / limitation states visible", () => {
    expect(complete).toContain("## 11. Data limitations and unresolved states");
    expect(complete).toContain(F.coverageRepairPlan.nonClaim);
    for (const u of missionJFixture().j3.unresolved) {
      expect(complete).toContain(u);
    }
    expect(jUnavailable).toContain(
      "- Mission J research record: unavailable — its measurement-limited and unresolved detail could not be exported (section 8).",
    );
    expect(iUnavailable).toContain(
      "- Mission I research record: unavailable — its structural-unavailability and fragility detail could not be exported (section 7).",
    );
    expect(gUnavailable).toContain(
      "- Mission G research record: unavailable — its limitation and falsifier detail could not be exported (section 6).",
    );
  });

  it("keeps the Mission I structural and knife-edge limitations in the limitations section", () => {
    const section = complete.split("## 11. Data limitations and unresolved states")[1]
      .split("## 12.")[0];
    expect(section).toContain("Mission I: FOMC 20d is structurally infeasible");
    expect(section).toContain("Mission I knife-edge fragility");
  });

  it("renders recorded provenance fields and says 'not recorded' for the rest", () => {
    expect(complete).toContain(`- Source commit: ${EIE.sourceCommit}`);
    expect(complete).toContain(`- Source document: ${EIE.sourceDoc}`);
    expect(complete).toContain(`- Source commit: ${MFE.sourceCommit}`);
    expect(complete).toContain(`- Source commit: ${RCL.sourceCommit}`);
    const j = missionJFixture();
    expect(complete).toContain(
      `- J1B artifact: ${j.provenance.sources.j1b.artifact} — sha256 ${j.provenance.sources.j1b.sha256} · ${j.provenance.sources.j1b.bytes} bytes`,
    );
    expect(complete).toContain("not recorded");
    // Mission G records no commit / hash / repro in its contract
    expect(complete).toContain("- Artifact hashes: not recorded");
  });

  it("renders reproduction commands as inline code, never as controls", () => {
    expect(complete).toContain(`- Reproduction: \`${EIE.reproCommand}\``);
    expect(complete).toContain(`- Reproduction: \`${MFE.reproCommand}\``);
    expect(complete).toContain(`- Reproduction: \`${FC.reproCommand}\``);
    expect(complete).toContain(
      `- Reproduction (any-support OR-rule ledger): \`${AC.orRuleRepro}\``,
    );
    expect(complete).toContain(
      `- Reproduction (directional-majority ledger): \`${AC.directionalMajority.repro}\``,
    );
    expect(complete).not.toContain("<button");
    expect(complete).not.toContain("<a href");
  });
});

// ---------------------------------------------------------------------------
// Banned framing — affirmative claims never appear; negated non-claims are
// permitted only inside negation lines or dedicated non-claim / claim-limit
// sections.
// ---------------------------------------------------------------------------

const BANNED = [
  /\bbuy\b/i,
  /\bsell\b/i,
  /\bsignal\b/i,
  /\bopportunity\b/i,
  /\balpha\b/i,
  /\btradeable\b/i,
  /\btradable\b/i,
  /validated strategy/i,
  /predictive accuracy/i,
  /statistically significant/i,
  /\bcaused\b/i,
  /\bproves\b/i,
];

const EXCLUDED_HEADING = /non-claims|claim ceiling|claim limits/i;
const NEGATION = /\b(not|no|never|none|non|without|unavailable)\b/i;

/** Split the memo into (headingLine, bodyLines[]) sections. */
function sections(memo: string): Array<{ heading: string; lines: string[] }> {
  const out: Array<{ heading: string; lines: string[] }> = [];
  let current = { heading: "", lines: [] as string[] };
  for (const line of memo.split("\n")) {
    if (/^#{1,4} /.test(line)) {
      out.push(current);
      current = { heading: line, lines: [] };
    } else {
      current.lines.push(line);
    }
  }
  out.push(current);
  return out;
}

describe("research-record memo — no banned framing", () => {
  it("carries banned tokens only in negated lines or dedicated non-claim sections", () => {
    for (const [name, memo] of allVariants) {
      for (const sec of sections(memo)) {
        if (EXCLUDED_HEADING.test(sec.heading)) continue;
        for (const line of sec.lines) {
          for (const banned of BANNED) {
            if (banned.test(line)) {
              expect(
                NEGATION.test(line),
                `${name}: affirmative banned token ${banned} in ${JSON.stringify(line)} under ${sec.heading}`,
              ).toBe(true);
            }
          }
        }
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Query-snapshot mapping and readiness
// ---------------------------------------------------------------------------

describe("research-record memo — export readiness and lane mapping", () => {
  const g = missionGFixture();
  const i = missionIFixture();
  const j = missionJFixture();
  const settledG = { isPending: false, isError: false, data: g };
  const settledI = { isPending: false, isError: false, data: i };
  const settledJ = { isPending: false, isError: false, data: j };
  const pending = { isPending: true, isError: false, data: undefined };
  const errored = { isPending: false, isError: true, data: undefined };

  it("is not ready while any of the three contracts is still in its initial loading state", () => {
    expect(researchRecordExportReady(pending, settledI, settledJ)).toBe(false);
    expect(researchRecordExportReady(settledG, pending, settledJ)).toBe(false);
    expect(researchRecordExportReady(settledG, settledI, pending)).toBe(false);
    expect(researchRecordExportReady(pending, pending, pending)).toBe(false);
  });

  it("is ready once all three queries settle, including settled errors", () => {
    expect(researchRecordExportReady(settledG, settledI, settledJ)).toBe(true);
    expect(researchRecordExportReady(errored, settledI, settledJ)).toBe(true);
    expect(researchRecordExportReady(settledG, errored, settledJ)).toBe(true);
    expect(researchRecordExportReady(settledG, settledI, errored)).toBe(true);
    expect(researchRecordExportReady(errored, errored, errored)).toBe(true);
  });

  it("maps settled data to available lanes and errors to explicit unavailable lanes", () => {
    const input = researchRecordMemoInput(settledG, settledI, settledJ, "2026-07-16T12:00:00Z");
    expect(input.missionG).toEqual({ available: true, data: g });
    expect(input.missionI).toEqual({ available: true, data: i });
    expect(input.missionJ).toEqual({ available: true, data: j });
    expect(input.exportedAt).toBe("2026-07-16T12:00:00Z");

    const degraded = researchRecordMemoInput(errored, errored, settledJ);
    expect(degraded.missionG).toEqual({ available: false });
    expect(degraded.missionI).toEqual({ available: false });
    expect(degraded.missionJ).toEqual({ available: true, data: j });
    expect(degraded.exportedAt).toBeUndefined();

    // no data (even without an error flag) never fabricates an available lane
    expect(
      researchRecordMemoInput(pending, pending, {
        isPending: false,
        isError: false,
        data: undefined,
      }).missionJ,
    ).toEqual({ available: false });
  });
});

// ---------------------------------------------------------------------------
// Download mechanics — separate helper, injected adapter
// ---------------------------------------------------------------------------

function fakeAdapter(clickError?: Error) {
  const calls = {
    blobs: [] as Blob[],
    urls: [] as string[],
    revoked: [] as string[],
    anchors: [] as MemoDownloadAnchor[],
    mounted: [] as MemoDownloadAnchor[],
    unmounted: [] as MemoDownloadAnchor[],
    clicks: 0,
  };
  const adapter: MemoDownloadAdapter = {
    createObjectURL(blob) {
      calls.blobs.push(blob);
      const url = `blob:fake-${calls.blobs.length}`;
      calls.urls.push(url);
      return url;
    },
    revokeObjectURL(url) {
      calls.revoked.push(url);
    },
    createAnchor() {
      const anchor: MemoDownloadAnchor = {
        href: "",
        download: "",
        click() {
          calls.clicks += 1;
          if (clickError) throw clickError;
        },
      };
      calls.anchors.push(anchor);
      return anchor;
    },
    mount(anchor) {
      calls.mounted.push(anchor);
    },
    unmount(anchor) {
      calls.unmounted.push(anchor);
    },
  };
  return { adapter, calls };
}

describe("research-record memo — download mechanics", () => {
  it("downloads one UTF-8 Markdown blob under the stable filename", async () => {
    const { adapter, calls } = fakeAdapter();
    downloadResearchRecordMemo(complete, RESEARCH_RECORD_FILENAME, adapter);
    expect(RESEARCH_RECORD_FILENAME).toBe("second-order-research-record.md");
    expect(RESEARCH_RECORD_MIME_TYPE).toBe("text/markdown;charset=utf-8");
    expect(calls.blobs).toHaveLength(1);
    expect(calls.blobs[0].type).toBe(RESEARCH_RECORD_MIME_TYPE);
    expect(await calls.blobs[0].text()).toBe(complete);
    expect(calls.anchors).toHaveLength(1);
    expect(calls.anchors[0].download).toBe("second-order-research-record.md");
    expect(calls.anchors[0].href).toBe(calls.urls[0]);
    expect(calls.clicks).toBe(1);
  });

  it("defaults to the stable filename", () => {
    const { adapter, calls } = fakeAdapter();
    downloadResearchRecordMemo(complete, undefined, adapter);
    expect(calls.anchors[0].download).toBe(RESEARCH_RECORD_FILENAME);
  });

  it("mounts and removes the temporary anchor and revokes the object URL", () => {
    const { adapter, calls } = fakeAdapter();
    downloadResearchRecordMemo(complete, RESEARCH_RECORD_FILENAME, adapter);
    expect(calls.mounted).toHaveLength(1);
    expect(calls.unmounted).toHaveLength(1);
    expect(calls.unmounted[0]).toBe(calls.mounted[0]);
    expect(calls.revoked).toEqual(calls.urls);
  });

  it("leaks no object URL across repeated invocations", () => {
    const { adapter, calls } = fakeAdapter();
    downloadResearchRecordMemo(complete, RESEARCH_RECORD_FILENAME, adapter);
    downloadResearchRecordMemo(complete, RESEARCH_RECORD_FILENAME, adapter);
    expect(calls.urls).toHaveLength(2);
    expect(calls.revoked).toEqual(calls.urls);
  });

  it("revokes the object URL and removes the anchor even if the click throws", () => {
    const { adapter, calls } = fakeAdapter(new Error("boom"));
    expect(() =>
      downloadResearchRecordMemo(complete, RESEARCH_RECORD_FILENAME, adapter),
    ).toThrow("boom");
    expect(calls.revoked).toEqual(calls.urls);
    expect(calls.unmounted).toHaveLength(1);
  });
});
