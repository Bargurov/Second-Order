/**
 * Contract-shaped Mission G fixture (mirrors GET /evidence/mission-g, the
 * H2 contract).  Values mirror the tracked research record; this fixture is
 * a shared test input (the card and page suites keep their own inline
 * copies from H3).  Not a test file — imported by the research-record memo
 * and export suites.
 */
import type { MissionGEvidenceSummary } from "@/lib/api";

export const MISSION_G_APPROVED_OPEC_WORDING =
  "stable descriptive association with unresolved calendar-time confounding";

export function missionGFixture(): MissionGEvidenceSummary {
  return {
    contract_version: "mission-g-evidence-v1",
    source_artifacts: {
      readout: "G6_FROZEN_MANIFEST_READOUT.md",
      stability: "G6B_STABILITY_AND_FALSIFIERS.md",
      cases: "G6C_REPRESENTATIVE_CASES.md",
      promotion_proof: "G5_PROMOTION_PROOF.md",
      mechanism_attrition: "G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
    },
    provenance: {
      sources: {
        readout: { artifact: "G6_FROZEN_MANIFEST_READOUT.md", sha256: "aa11d06a0f1e", bytes: 21001 },
        stability: { artifact: "G6B_STABILITY_AND_FALSIFIERS.md", sha256: "bb22d06b57ab", bytes: 19002 },
        cases: { artifact: "G6C_REPRESENTATIVE_CASES.md", sha256: "cc33d06cca5e", bytes: 15003 },
        promotion_proof: { artifact: "G5_PROMOTION_PROOF.md", sha256: "dd44d0557001", bytes: 9004 },
        mechanism_attrition: { artifact: "G3_MECHANISM_CLASSIFICATION_ATTRITION.md", sha256: "ee55d03ba771", bytes: 7005 },
      },
      reproduction: {
        // The commands RECORDED in each publication's fenced Reproduction
        // block (verbatim, inert display strings).
        commands: {
          readout: [
            "python scripts/g6_frozen_manifest_readout.py --emit",
            "python -m unittest tests.test_g6_frozen_manifest_readout",
          ],
          stability: [
            "python scripts/g6b_stability_falsifiers.py --emit",
            "python -m unittest tests.test_g6b_stability_falsifiers",
          ],
          cases: [
            "python scripts/g6c_representative_cases.py --emit",
            "python -m unittest tests.test_g6c_representative_cases",
          ],
          promotion_proof: [
            "python -m unittest tests.test_g5_promotion",
            "python scripts/g5_promotion.py --verify            # read-only live probe",
            "python scripts/g5_promotion.py --temp-proof COPY   # full proof on a copy",
          ],
          mechanism_attrition: [
            "python scripts/g3_mechanism_classification.py --classify",
            "python scripts/g3_mechanism_classification.py --emit-report",
            "python -m unittest tests.test_g3_mechanism_classification",
          ],
        },
        recorded_in: {
          readout: "G6_FROZEN_MANIFEST_READOUT.md",
          stability: "G6B_STABILITY_AND_FALSIFIERS.md",
          cases: "G6C_REPRESENTATIVE_CASES.md",
          promotion_proof: "G5_PROMOTION_PROOF.md",
          mechanism_attrition: "G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
        },
      },
      execution_commits: null,
      computation_dates: null,
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
      wording: MISSION_G_APPROVED_OPEC_WORDING,
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
