/**
 * H3 — Mission G historical-evidence card render contract.
 *
 * The card is the first in-product consumer of the completed Mission G
 * record (GET /evidence/mission-g).  It must:
 *   - show the evidence ARCHITECTURE first: accepted 86 and historical 97
 *     as separate lanes (65 FOMC + 32 OPEC as children of 97), with the
 *     pooling prohibition visible and no combined 183 anywhere;
 *   - lead the results with the broad null and the 44/120 / 76/120
 *     stability reversals (never a tooltip);
 *   - render the bounded OPEC association AFTER the null, using the exact
 *     approved wording verbatim, with its confound limitation attached;
 *   - keep failures visible: era-bounded secondary credit (36/97) and the
 *     G3B mechanism-comparability failure;
 *   - list the six representative cases as illustrations, never proof;
 *   - be honest when data is loading or unavailable (no fake values);
 *   - carry no banned trade / signal / overclaim framing.
 *
 * Presentational only — no React Query, no network.  Pattern mirrors
 * tracked-evidence-card.test.tsx / evidence-coverage-card.test.tsx:
 * vitest + renderToStaticMarkup, no jsdom.  The fixture is contract-shaped
 * (mirrors the H2 response) and is the only place test values live.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { MissionGEvidenceSummary } from "@/lib/api";
import { MissionGEvidenceCard } from "../mission-g-evidence-card";

// ---------------------------------------------------------------------------
// Contract-shaped fixture (mirrors GET /evidence/mission-g).
// ---------------------------------------------------------------------------

const APPROVED_WORDING =
  "stable descriptive association with unresolved calendar-time confounding";

function fixture(): MissionGEvidenceSummary {
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
      wording: APPROVED_WORDING,
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

function render(props: Parameters<typeof MissionGEvidenceCard>[0]): string {
  return renderToStaticMarkup(<MissionGEvidenceCard {...props} />);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MissionGEvidenceCard", () => {
  it("renders accepted 86 and historical 97 as separate lanes, architecture first", () => {
    const html = render({ data: fixture() });
    expect(html).toContain("86");
    expect(html).toContain("97");
    expect(html.toLowerCase()).toContain("never pooled");
    // architecture (lane split) must precede the results
    const laneIdx = html.indexOf("Accepted track record");
    const nullIdx = html.indexOf("broadly null");
    expect(laneIdx).toBeGreaterThan(-1);
    expect(nullIdx).toBeGreaterThan(-1);
    expect(laneIdx).toBeLessThan(nullIdx);
  });

  it("keeps 65 FOMC and 32 OPEC as children of the historical 97", () => {
    const html = render({ data: fixture() });
    const hist = html.indexOf("Historical evidence");
    const fomc = html.indexOf("65");
    const opec = html.indexOf("32");
    expect(hist).toBeGreaterThan(-1);
    expect(fomc).toBeGreaterThan(hist);
    expect(opec).toBeGreaterThan(hist);
    expect(html).toContain("FOMC");
    expect(html).toContain("OPEC");
  });

  it("never presents a combined 183 sample", () => {
    const html = render({ data: fixture() });
    expect(html).not.toContain("183");
  });

  it("leads results with the broad null before the bounded OPEC association", () => {
    const html = render({ data: fixture() });
    const nullIdx = html.indexOf("broadly null");
    const opecIdx = html.indexOf(APPROVED_WORDING);
    expect(nullIdx).toBeGreaterThan(-1);
    expect(opecIdx).toBeGreaterThan(-1);
    expect(nullIdx).toBeLessThan(opecIdx);
  });

  it("shows the 44/120 and 76/120 instability diagnostics in plain text", () => {
    const html = render({ data: fixture() });
    expect(html).toContain("44/120");
    expect(html).toContain("76/120");
  });

  it("renders the approved OPEC wording verbatim with its confound attached", () => {
    const html = render({ data: fixture() });
    expect(html).toContain(APPROVED_WORDING);
    expect(html.toLowerCase()).toContain("cannot separate state from era");
  });

  it("carries no banned framing anywhere", () => {
    const html = render({ data: fixture() }).toLowerCase();
    for (const banned of [
      "validated",
      "causal",
      "predictive",
      "signal",
      "strongest",
      "robust relationship",
      "actionable",
      "top finding",
      "winner",
      "alpha",
    ]) {
      expect(html, banned).not.toContain(banned);
    }
  });

  it("shows the era-bounded secondary credit limitation with 36/97", () => {
    const html = render({ data: fixture() });
    expect(html).toContain("36/97");
    expect(html.toLowerCase()).toContain("era-bounded");
    expect(html.toLowerCase()).toContain("secondary");
  });

  it("keeps the G3B mechanism-comparability failure visible as a result", () => {
    const html = render({ data: fixture() });
    expect(html.toLowerCase()).toContain("did not transfer comparably");
    expect(html).toContain("79.1");
  });

  it("labels the six cases as illustrations, never proof", () => {
    const html = render({ data: fixture() });
    expect(html).toContain("illustrations, never proof");
    expect(html).toContain("opec-2024-11-03-one-month-delay");
    expect(html).toContain("fomc-policy-decision-2018-05-02");
    const caseIds = (html.match(/opec-20|fomc-policy-decision/g) ?? []).length;
    expect(caseIds).toBe(6);
  });

  it("renders an honest loading state when data is absent", () => {
    const html = render({ data: undefined });
    expect(html.toLowerCase()).toContain("loading");
    expect(html).not.toContain("44/120");
  });

  it("renders an explicit unavailable state instead of fake values", () => {
    const html = render({ data: undefined, unavailable: true });
    expect(html.toLowerCase()).toContain("unavailable");
    expect(html).not.toContain("44/120");
    expect(html).not.toContain("86");
  });
});
