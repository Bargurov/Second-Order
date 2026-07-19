/**
 * U1 parity fixture — a GENERATED capture of the real universal event
 * dossier producer responses, taken through the FastAPI HTTP layer
 * (TestClient against api.py with an isolated temporary EVENTS_DB_FILE
 * and provider keys explicitly empty).  No value below was hand-retyped
 * and no research value is recomputed here; if the tracked publications
 * ever change, re-run the capture — never hand-edit this file.
 *
 *   GET /evidence/event-dossiers                 -> eventDossierIndexFixture()
 *   GET /evidence/event-dossiers/{candidate_id}  -> eventDossierDetailFixture(key)
 *
 * The four detail probes cover the four published tiers x families
 * (FOMC/OPEC x published_per_event_dossier/core_published_evidence).
 * Probe ids are parity fixtures, not featured or representative cases.
 * Not a test file - imported by the universal-event-dossier suites.
 */
import type { EventDossierDetail, EventDossierIndex } from "@/lib/api";

export const EVENT_DOSSIER_PROBE_IDS = {
  "fomc_enriched": "fomc-policy-decision-2018-05-02",
  "fomc_core": "fomc-policy-decision-2018-01-31",
  "opec_enriched": "opec-2023-11-30-voluntary-2p2",
  "opec_core": "opec-2018-06-23-conformity-return"
} as const;

export type EventDossierProbeKey = keyof typeof EVENT_DOSSIER_PROBE_IDS;

/** Fresh deep copy per call so mutation tests never leak. */
export function eventDossierIndexFixture(): EventDossierIndex {
  return structuredClone(EVENT_DOSSIER_INDEX);
}

/** Fresh deep copy per call so mutation tests never leak. */
export function eventDossierDetailFixture(
  key: EventDossierProbeKey,
): EventDossierDetail {
  return structuredClone(EVENT_DOSSIER_DETAILS[key]);
}

const EVENT_DOSSIER_INDEX: EventDossierIndex = {
  "contract_version": "event-dossier-index-v1",
  "universe": "historical_research",
  "generated_from": [
    {
      "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
      "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
      "bytes": 101773,
      "note": "Mission I event-level surface via mission-i-evidence-v2"
    },
    {
      "artifact": "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
      "sha256": "b16d5863fda0541c43ff5a75dfb8e6c76a92af46f92c7971a8390f56132a9964",
      "bytes": 5073,
      "note": "Mission I candidate-universe funnel"
    },
    {
      "artifact": "stats/I2C_FALSIFIERS.md",
      "sha256": "86dcf82ad4e8381695451db19d0b64f47abc9c353ed24ac1433e70857963d7d5",
      "bytes": 59232,
      "note": "Mission I falsifier battery publication"
    },
    {
      "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
      "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
      "bytes": 39855,
      "note": "frame-complete FOMC identity and source ledger"
    },
    {
      "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
      "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
      "bytes": 20695,
      "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
    },
    {
      "artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md",
      "sha256": "61921026c78df980353461f808e8ff184a774614a5f24db51cdc48a20a083167",
      "bytes": 5978,
      "note": "canonical frozen family mapping (g3-transmission-map-v1)"
    },
    {
      "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
      "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
      "bytes": 6584,
      "note": "Mission G evidence source (mechanism_attrition)"
    },
    {
      "artifact": "stats/G5_PROMOTION_PROOF.md",
      "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
      "bytes": 9188,
      "note": "Mission G evidence source (promotion_proof)"
    },
    {
      "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
      "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
      "bytes": 39790,
      "note": "Mission G evidence source (readout)"
    },
    {
      "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
      "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
      "bytes": 46080,
      "note": "Mission G evidence source (stability)"
    },
    {
      "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
      "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
      "bytes": 14476,
      "note": "Mission J evidence source (j1b)"
    },
    {
      "artifact": "stats/J2_TIMING_COLLISION_RESULTS.md",
      "sha256": "f51e58e3705933f53a4f3d8381ab6795e9aa5119281c73638f9b5d50a9015d97",
      "bytes": 18563,
      "note": "Mission J evidence source (j2)"
    },
    {
      "artifact": "stats/J3_MECHANISM_TRANSMISSION_READOUT.md",
      "sha256": "41e73b5cbe82dec11351bdf4d8f06c0715d4d56074e14fe275c6ba3fcbe16aef",
      "bytes": 12175,
      "note": "Mission J evidence source (j3)"
    },
    {
      "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
      "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
      "bytes": 21943,
      "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
    }
  ],
  "coverage": {
    "total": 97,
    "family_counts": {
      "FOMC": 65,
      "OPEC": 32
    },
    "status_counts": {
      "COMPLETE": 97,
      "PARTIAL": 0,
      "UNAVAILABLE": 0,
      "CONTRADICTORY": 0
    },
    "section_availability_counts": {
      "identity": {
        "available": 97
      },
      "source_provenance": {
        "available": 97
      },
      "eligibility_denominators": {
        "available": 97
      },
      "mechanism_asset_basis": {
        "available": 97
      },
      "reaction_observations": {
        "available": 97
      },
      "reaction_enrichment": {
        "not_exposed": 91,
        "available": 6
      },
      "ordinary_period_context": {
        "available": 97
      },
      "aggregate_research_context": {
        "available": 97
      },
      "robustness_timing_transmission": {
        "available": 97
      },
      "falsifier_fragility": {
        "available": 97
      },
      "missingness_limitations": {
        "available": 97
      },
      "evidence_class_claim_ceiling": {
        "available": 97
      },
      "non_claim": {
        "available": 97
      }
    },
    "enrichment_counts": {
      "published_per_event_dossier": 6,
      "core_published_evidence": 91
    },
    "contradiction_counts": {
      "events": 0,
      "sections": 0
    }
  },
  "events": [
    {
      "candidate_id": "fomc-policy-decision-2018-01-31",
      "family": "FOMC",
      "event_date": "2018-01-31",
      "anchor_session": "2018-01-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-03-21",
      "family": "FOMC",
      "event_date": "2018-03-21",
      "anchor_session": "2018-03-21",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-05-02",
      "family": "FOMC",
      "event_date": "2018-05-02",
      "anchor_session": "2018-05-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 13,
      "unavailable_section_count": 0,
      "contradictory_section_count": 0,
      "enrichment_tier": "published_per_event_dossier"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-06-13",
      "family": "FOMC",
      "event_date": "2018-06-13",
      "anchor_session": "2018-06-13",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-08-01",
      "family": "FOMC",
      "event_date": "2018-08-01",
      "anchor_session": "2018-08-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-09-26",
      "family": "FOMC",
      "event_date": "2018-09-26",
      "anchor_session": "2018-09-26",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-11-08",
      "family": "FOMC",
      "event_date": "2018-11-08",
      "anchor_session": "2018-11-08",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2018-12-19",
      "family": "FOMC",
      "event_date": "2018-12-19",
      "anchor_session": "2018-12-19",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-01-30",
      "family": "FOMC",
      "event_date": "2019-01-30",
      "anchor_session": "2019-01-30",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-03-20",
      "family": "FOMC",
      "event_date": "2019-03-20",
      "anchor_session": "2019-03-20",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-05-01",
      "family": "FOMC",
      "event_date": "2019-05-01",
      "anchor_session": "2019-05-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-06-19",
      "family": "FOMC",
      "event_date": "2019-06-19",
      "anchor_session": "2019-06-19",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-07-31",
      "family": "FOMC",
      "event_date": "2019-07-31",
      "anchor_session": "2019-07-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-09-18",
      "family": "FOMC",
      "event_date": "2019-09-18",
      "anchor_session": "2019-09-18",
      "top_level_status": "COMPLETE",
      "available_section_count": 13,
      "unavailable_section_count": 0,
      "contradictory_section_count": 0,
      "enrichment_tier": "published_per_event_dossier"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-10-30",
      "family": "FOMC",
      "event_date": "2019-10-30",
      "anchor_session": "2019-10-30",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2019-12-11",
      "family": "FOMC",
      "event_date": "2019-12-11",
      "anchor_session": "2019-12-11",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-01-29",
      "family": "FOMC",
      "event_date": "2020-01-29",
      "anchor_session": "2020-01-29",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-03-03",
      "family": "FOMC",
      "event_date": "2020-03-03",
      "anchor_session": "2020-03-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-03-15",
      "family": "FOMC",
      "event_date": "2020-03-15",
      "anchor_session": "2020-03-13",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-04-29",
      "family": "FOMC",
      "event_date": "2020-04-29",
      "anchor_session": "2020-04-29",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-06-10",
      "family": "FOMC",
      "event_date": "2020-06-10",
      "anchor_session": "2020-06-10",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-07-29",
      "family": "FOMC",
      "event_date": "2020-07-29",
      "anchor_session": "2020-07-29",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-09-16",
      "family": "FOMC",
      "event_date": "2020-09-16",
      "anchor_session": "2020-09-16",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-11-05",
      "family": "FOMC",
      "event_date": "2020-11-05",
      "anchor_session": "2020-11-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2020-12-16",
      "family": "FOMC",
      "event_date": "2020-12-16",
      "anchor_session": "2020-12-16",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-01-27",
      "family": "FOMC",
      "event_date": "2021-01-27",
      "anchor_session": "2021-01-27",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-03-17",
      "family": "FOMC",
      "event_date": "2021-03-17",
      "anchor_session": "2021-03-17",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-04-28",
      "family": "FOMC",
      "event_date": "2021-04-28",
      "anchor_session": "2021-04-28",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-06-16",
      "family": "FOMC",
      "event_date": "2021-06-16",
      "anchor_session": "2021-06-16",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-07-28",
      "family": "FOMC",
      "event_date": "2021-07-28",
      "anchor_session": "2021-07-28",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-09-22",
      "family": "FOMC",
      "event_date": "2021-09-22",
      "anchor_session": "2021-09-22",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-11-03",
      "family": "FOMC",
      "event_date": "2021-11-03",
      "anchor_session": "2021-11-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2021-12-15",
      "family": "FOMC",
      "event_date": "2021-12-15",
      "anchor_session": "2021-12-15",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-01-26",
      "family": "FOMC",
      "event_date": "2022-01-26",
      "anchor_session": "2022-01-26",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-03-16",
      "family": "FOMC",
      "event_date": "2022-03-16",
      "anchor_session": "2022-03-16",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-05-04",
      "family": "FOMC",
      "event_date": "2022-05-04",
      "anchor_session": "2022-05-04",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-06-15",
      "family": "FOMC",
      "event_date": "2022-06-15",
      "anchor_session": "2022-06-15",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-07-27",
      "family": "FOMC",
      "event_date": "2022-07-27",
      "anchor_session": "2022-07-27",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-09-21",
      "family": "FOMC",
      "event_date": "2022-09-21",
      "anchor_session": "2022-09-21",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-11-02",
      "family": "FOMC",
      "event_date": "2022-11-02",
      "anchor_session": "2022-11-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2022-12-14",
      "family": "FOMC",
      "event_date": "2022-12-14",
      "anchor_session": "2022-12-14",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-02-01",
      "family": "FOMC",
      "event_date": "2023-02-01",
      "anchor_session": "2023-02-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-03-22",
      "family": "FOMC",
      "event_date": "2023-03-22",
      "anchor_session": "2023-03-22",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-05-03",
      "family": "FOMC",
      "event_date": "2023-05-03",
      "anchor_session": "2023-05-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-06-14",
      "family": "FOMC",
      "event_date": "2023-06-14",
      "anchor_session": "2023-06-14",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-07-26",
      "family": "FOMC",
      "event_date": "2023-07-26",
      "anchor_session": "2023-07-26",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-09-20",
      "family": "FOMC",
      "event_date": "2023-09-20",
      "anchor_session": "2023-09-20",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-11-01",
      "family": "FOMC",
      "event_date": "2023-11-01",
      "anchor_session": "2023-11-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2023-12-13",
      "family": "FOMC",
      "event_date": "2023-12-13",
      "anchor_session": "2023-12-13",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-01-31",
      "family": "FOMC",
      "event_date": "2024-01-31",
      "anchor_session": "2024-01-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-03-20",
      "family": "FOMC",
      "event_date": "2024-03-20",
      "anchor_session": "2024-03-20",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-05-01",
      "family": "FOMC",
      "event_date": "2024-05-01",
      "anchor_session": "2024-05-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-06-12",
      "family": "FOMC",
      "event_date": "2024-06-12",
      "anchor_session": "2024-06-12",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-07-31",
      "family": "FOMC",
      "event_date": "2024-07-31",
      "anchor_session": "2024-07-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-09-18",
      "family": "FOMC",
      "event_date": "2024-09-18",
      "anchor_session": "2024-09-18",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-11-07",
      "family": "FOMC",
      "event_date": "2024-11-07",
      "anchor_session": "2024-11-07",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2024-12-18",
      "family": "FOMC",
      "event_date": "2024-12-18",
      "anchor_session": "2024-12-18",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-01-29",
      "family": "FOMC",
      "event_date": "2025-01-29",
      "anchor_session": "2025-01-29",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-03-19",
      "family": "FOMC",
      "event_date": "2025-03-19",
      "anchor_session": "2025-03-19",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-05-07",
      "family": "FOMC",
      "event_date": "2025-05-07",
      "anchor_session": "2025-05-07",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-06-18",
      "family": "FOMC",
      "event_date": "2025-06-18",
      "anchor_session": "2025-06-18",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-07-30",
      "family": "FOMC",
      "event_date": "2025-07-30",
      "anchor_session": "2025-07-30",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-09-17",
      "family": "FOMC",
      "event_date": "2025-09-17",
      "anchor_session": "2025-09-17",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-10-29",
      "family": "FOMC",
      "event_date": "2025-10-29",
      "anchor_session": "2025-10-29",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "fomc-policy-decision-2025-12-10",
      "family": "FOMC",
      "event_date": "2025-12-10",
      "anchor_session": "2025-12-10",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2018-06-23-conformity-return",
      "family": "OPEC",
      "event_date": "2018-06-23",
      "anchor_session": "2018-06-22",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2018-12-07-cut-1p2",
      "family": "OPEC",
      "event_date": "2018-12-07",
      "anchor_session": "2018-12-07",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2019-07-02-extension",
      "family": "OPEC",
      "event_date": "2019-07-02",
      "anchor_session": "2019-07-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2019-12-06-deepen-1p7",
      "family": "OPEC",
      "event_date": "2019-12-06",
      "anchor_session": "2019-12-06",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2020-04-12-cut-9p7",
      "family": "OPEC",
      "event_date": "2020-04-12",
      "anchor_session": "2020-04-09",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2020-06-06-extension",
      "family": "OPEC",
      "event_date": "2020-06-06",
      "anchor_session": "2020-06-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2020-12-03-restoration-start",
      "family": "OPEC",
      "event_date": "2020-12-03",
      "anchor_session": "2020-12-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2021-01-05-feb-mar-levels",
      "family": "OPEC",
      "event_date": "2021-01-05",
      "anchor_session": "2021-01-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2021-04-01-gradual-return",
      "family": "OPEC",
      "event_date": "2021-04-01",
      "anchor_session": "2021-04-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2021-07-18-monthly-400k",
      "family": "OPEC",
      "event_date": "2021-07-18",
      "anchor_session": "2021-07-16",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2022-06-02-accelerate-648k",
      "family": "OPEC",
      "event_date": "2022-06-02",
      "anchor_session": "2022-06-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2022-08-03-sep-100k",
      "family": "OPEC",
      "event_date": "2022-08-03",
      "anchor_session": "2022-08-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2022-09-05-oct-minus-100k",
      "family": "OPEC",
      "event_date": "2022-09-05",
      "anchor_session": "2022-09-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2022-10-05-cut-2mbd",
      "family": "OPEC",
      "event_date": "2022-10-05",
      "anchor_session": "2022-10-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2023-04-02-voluntary-1p16",
      "family": "OPEC",
      "event_date": "2023-04-02",
      "anchor_session": "2023-03-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2023-06-04-2024-levels",
      "family": "OPEC",
      "event_date": "2023-06-04",
      "anchor_session": "2023-06-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2023-11-30-voluntary-2p2",
      "family": "OPEC",
      "event_date": "2023-11-30",
      "anchor_session": "2023-11-30",
      "top_level_status": "COMPLETE",
      "available_section_count": 13,
      "unavailable_section_count": 0,
      "contradictory_section_count": 0,
      "enrichment_tier": "published_per_event_dossier"
    },
    {
      "candidate_id": "opec-2024-03-03-q2-extension",
      "family": "OPEC",
      "event_date": "2024-03-03",
      "anchor_session": "2024-03-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 13,
      "unavailable_section_count": 0,
      "contradictory_section_count": 0,
      "enrichment_tier": "published_per_event_dossier"
    },
    {
      "candidate_id": "opec-2024-06-02-extension-schedule",
      "family": "OPEC",
      "event_date": "2024-06-02",
      "anchor_session": "2024-05-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2024-09-05-two-month-delay",
      "family": "OPEC",
      "event_date": "2024-09-05",
      "anchor_session": "2024-09-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2024-11-03-one-month-delay",
      "family": "OPEC",
      "event_date": "2024-11-03",
      "anchor_session": "2024-11-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 13,
      "unavailable_section_count": 0,
      "contradictory_section_count": 0,
      "enrichment_tier": "published_per_event_dossier"
    },
    {
      "candidate_id": "opec-2024-12-05-april-start",
      "family": "OPEC",
      "event_date": "2024-12-05",
      "anchor_session": "2024-12-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-03-03-activation",
      "family": "OPEC",
      "event_date": "2025-03-03",
      "anchor_session": "2025-03-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-04-03-may-411k",
      "family": "OPEC",
      "event_date": "2025-04-03",
      "anchor_session": "2025-04-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-05-03-jun-411k",
      "family": "OPEC",
      "event_date": "2025-05-03",
      "anchor_session": "2025-05-02",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-06-01-jul-411k",
      "family": "OPEC",
      "event_date": "2025-06-01",
      "anchor_session": "2025-05-30",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-07-05-aug-548k",
      "family": "OPEC",
      "event_date": "2025-07-05",
      "anchor_session": "2025-07-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-08-03-sep-547k",
      "family": "OPEC",
      "event_date": "2025-08-03",
      "anchor_session": "2025-08-01",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-09-07-oct-137k",
      "family": "OPEC",
      "event_date": "2025-09-07",
      "anchor_session": "2025-09-05",
      "top_level_status": "COMPLETE",
      "available_section_count": 13,
      "unavailable_section_count": 0,
      "contradictory_section_count": 0,
      "enrichment_tier": "published_per_event_dossier"
    },
    {
      "candidate_id": "opec-2025-10-05-nov-137k",
      "family": "OPEC",
      "event_date": "2025-10-05",
      "anchor_session": "2025-10-03",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-11-02-dec-137k-pause",
      "family": "OPEC",
      "event_date": "2025-11-02",
      "anchor_session": "2025-10-31",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    },
    {
      "candidate_id": "opec-2025-11-30-2026-hold",
      "family": "OPEC",
      "event_date": "2025-11-30",
      "anchor_session": "2025-11-28",
      "top_level_status": "COMPLETE",
      "available_section_count": 12,
      "unavailable_section_count": 1,
      "contradictory_section_count": 0,
      "enrichment_tier": "core_published_evidence"
    }
  ]
};

const EVENT_DOSSIER_DETAILS: Record<EventDossierProbeKey, EventDossierDetail> = {
  "fomc_enriched": {
    "contract_version": "event-dossier-v1",
    "candidate_id": "fomc-policy-decision-2018-05-02",
    "top_level_status": "COMPLETE",
    "enrichment_tier": "published_per_event_dossier",
    "sections": {
      "identity": {
        "status": "available",
        "reason_code": "exact_slug_join",
        "summary": "Exact identity join between the family identity ledger and the Mission I event-level surface; event date and anchor session are kept separate.",
        "data": {
          "candidate_id": "fomc-policy-decision-2018-05-02",
          "family": "FOMC",
          "event_date": "2018-05-02",
          "anchor_session": "2018-05-02",
          "identity_status": "exact_join"
        },
        "source_references": [
          {
            "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
            "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
            "bytes": 39855,
            "note": "frame-complete FOMC identity and source ledger"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "source_provenance": {
        "status": "available",
        "reason_code": "tracked_ledger_row",
        "summary": "Official dated source pinned in the tracked identity ledger; the untracked local archive is never consulted.",
        "data": {
          "source_description": "Maintain target range at 1.50-1.75 percent",
          "official_source_reference": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20180502a.htm",
          "source_artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
          "source_row_key": "fomc-policy-decision-2018-05-02",
          "artifact_sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
          "anchor_quality": "scheduled_or_weak_anchor",
          "publication_timestamp": "2:00 p.m. EDT",
          "schedule_status": "scheduled"
        },
        "source_references": [
          {
            "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
            "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
            "bytes": 39855,
            "note": "frame-complete FOMC identity and source ledger"
          }
        ]
      },
      "eligibility_denominators": {
        "status": "available",
        "reason_code": "mission_i_universe_lane",
        "summary": "FOMC family denominator and per-horizon ordinary reference denominators from the frozen Mission I universe funnel; the two family ledgers are never pooled.",
        "data": {
          "family_event_n": 65,
          "family_event_n_attempted": 65,
          "reference_n_by_horizon": {
            "1d": {
              "reference_n_attempted": 1816,
              "reference_n_available": 1816,
              "non_overlapping_blocks": 927,
              "status": "feasible"
            },
            "5d": {
              "reference_n_attempted": 1299,
              "reference_n_available": 1299,
              "non_overlapping_blocks": 233,
              "status": "feasible"
            },
            "20d": {
              "reference_n_attempted": 0,
              "reference_n_available": 0,
              "non_overlapping_blocks": 0,
              "status": "structurally_infeasible"
            }
          },
          "available_horizons": [
            "1d",
            "5d"
          ],
          "unavailable_horizons": [
            "20d"
          ],
          "eligibility_gate": "frozen I1 candidate-universe funnel (era, estimation, forward, gap, and exclusion cuts)"
        },
        "source_references": [
          {
            "artifact": "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
            "sha256": "b16d5863fda0541c43ff5a75dfb8e6c76a92af46f92c7971a8390f56132a9964",
            "bytes": 5073,
            "note": "Mission I candidate-universe funnel"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "mechanism_asset_basis": {
        "status": "available",
        "reason_code": "canonical_g3_family_mapping",
        "summary": "Frozen family-level transmission mapping from the tracked G3 mapping contract - family context, not a bespoke event-level causal finding.",
        "data": {
          "mechanism_hypothesis": "policy decision -> policy path / funding and curve conditions -> regional-bank equities",
          "mechanism_role": "family-level frozen mapping context; not an event-level causal finding",
          "scope": "family_level",
          "primary_asset": "KRE",
          "market_benchmark": "SPY",
          "sector_benchmark": "XLF",
          "price_basis_policy": "Raw-only sessions (adjusted basis unavailable): 0 — F3 basis is uniformly adjusted, no cross-basis pairing.",
          "claim_ceiling": "KRE is one predeclared second-order equity transmission lens for FOMC decisions. It is not the complete market reaction to monetary policy and does not imply every FOMC decision should move regional banks in one direction.",
          "mapping_version": {
            "status": "available",
            "value": "g3-transmission-map-v1",
            "source_artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md",
            "sha256": "61921026c78df980353461f808e8ff184a774614a5f24db51cdc48a20a083167",
            "bytes": 5978,
            "note": "canonical frozen family mapping (g3-transmission-map-v1)"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_observations": {
        "status": "available",
        "reason_code": "mission_i_event_level_rows",
        "summary": "Every published per-event observation for this event from the Mission I event-level surface, in publication order.",
        "data": {
          "rows": [
            {
              "horizon": "1d",
              "metric": "raw_return",
              "response": "-0.009843",
              "abs_mid_rank_pct": "0.485683",
              "signed_pct": "0.244493"
            },
            {
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "response": "-0.007640",
              "abs_mid_rank_pct": "0.487335",
              "signed_pct": "0.258260"
            },
            {
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "response": "-0.001372",
              "abs_mid_rank_pct": "0.154185",
              "signed_pct": "0.435022"
            },
            {
              "horizon": "1d",
              "metric": "sar",
              "response": "-0.814767",
              "abs_mid_rank_pct": "0.645925",
              "signed_pct": "0.172907"
            },
            {
              "horizon": "5d",
              "metric": "raw_return",
              "response": "0.026142",
              "abs_mid_rank_pct": "0.535027",
              "signed_pct": "0.742109"
            },
            {
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "response": "0.002206",
              "abs_mid_rank_pct": "0.066205",
              "signed_pct": "0.568899"
            },
            {
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "response": "-0.007007",
              "abs_mid_rank_pct": "0.294072",
              "signed_pct": "0.381832"
            },
            {
              "horizon": "5d",
              "metric": "sar",
              "response": "0.105204",
              "abs_mid_rank_pct": "0.083911",
              "signed_pct": "0.578137"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score."
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_enrichment": {
        "status": "available",
        "reason_code": "g6c_published_per_event_dossier",
        "summary": "Published G6C per-event dossier: four-lens 1d/5d/20d readout and role wording - illustration-only enrichment, never proof and never a universe.",
        "data": {
          "readout_rows": [
            {
              "metric": "absolute asset return",
              "1d": "-0.98%",
              "5d": "+2.61%",
              "20d": "+1.95%"
            },
            {
              "metric": "SPY-relative AR",
              "1d": "-0.76%",
              "5d": "+0.22%",
              "20d": "-0.99%"
            },
            {
              "metric": "sector-relative AR",
              "1d": "-0.14%",
              "5d": "-0.70%",
              "20d": "+1.84%"
            },
            {
              "metric": "SAR",
              "1d": "-0.81",
              "5d": "+0.11",
              "20d": "-0.24"
            }
          ],
          "role_in_record": "illustrates broad null or contradiction.",
          "source_description": "Maintain target range at 1.50-1.75 percent",
          "source_ledger_reference": "[Fed statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20180502a.htm)"
        },
        "source_references": [
          {
            "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
            "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
            "bytes": 21943,
            "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
          }
        ]
      },
      "ordinary_period_context": {
        "status": "available",
        "reason_code": "mission_i_cells_joined",
        "summary": "This event's published observations joined to their frozen ordinary-period cells with both denominators and the published aggregates visible.",
        "data": {
          "rows": [
            {
              "cell_key": "FOMC|1d|raw_return",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "raw_return",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.674559",
              "published_signed_percentile_median": "0.339207",
              "event_response": "-0.009843",
              "abs_mid_rank_pct": "0.485683",
              "signed_pct": "0.244493"
            },
            {
              "cell_key": "FOMC|1d|spy_relative_ar",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.672357",
              "published_signed_percentile_median": "0.405286",
              "event_response": "-0.007640",
              "abs_mid_rank_pct": "0.487335",
              "signed_pct": "0.258260"
            },
            {
              "cell_key": "FOMC|1d|sector_relative_ar",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.662996",
              "published_signed_percentile_median": "0.386013",
              "event_response": "-0.001372",
              "abs_mid_rank_pct": "0.154185",
              "signed_pct": "0.435022"
            },
            {
              "cell_key": "FOMC|1d|sar",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "sar",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.725771",
              "published_signed_percentile_median": "0.377753",
              "event_response": "-0.814767",
              "abs_mid_rank_pct": "0.645925",
              "signed_pct": "0.172907"
            },
            {
              "cell_key": "FOMC|5d|raw_return",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "raw_return",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.501155",
              "published_signed_percentile_median": "0.447267",
              "event_response": "0.026142",
              "abs_mid_rank_pct": "0.535027",
              "signed_pct": "0.742109"
            },
            {
              "cell_key": "FOMC|5d|spy_relative_ar",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.527329",
              "published_signed_percentile_median": "0.504234",
              "event_response": "0.002206",
              "abs_mid_rank_pct": "0.066205",
              "signed_pct": "0.568899"
            },
            {
              "cell_key": "FOMC|5d|sector_relative_ar",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.408006",
              "published_signed_percentile_median": "0.501925",
              "event_response": "-0.007007",
              "abs_mid_rank_pct": "0.294072",
              "signed_pct": "0.381832"
            },
            {
              "cell_key": "FOMC|5d|sar",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "sar",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.556582",
              "published_signed_percentile_median": "0.505004",
              "event_response": "0.105204",
              "abs_mid_rank_pct": "0.083911",
              "signed_pct": "0.578137"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score.",
          "fomc_20d": {
            "status": "structurally_unavailable",
            "reason_code": "fomc_20d_ordinary_substrate_unavailable",
            "limitation": "The 20d horizon is structurally infeasible: with the estimation and forward gates removing nothing in-era, the exclusion geometry alone leaves zero eligible sessions — a pre-declared calendar fact (I0 §8), not a data gap and not rescued by any substitute date."
          }
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "aggregate_research_context": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published aggregate conclusions for this event's family - context for reading the event, never an individual-event label.",
        "data": {
          "contexts": [
            {
              "context_scope": "aggregate",
              "source": "mission_i",
              "evidence_class": "Mission I descriptive / comparative ordinary-period evidence",
              "family_readouts": [
                {
                  "horizon": "1d",
                  "headline": "FOMC decision windows show a broad, perturbation-stable elevation in one-day response magnitude relative to era-matched ordinary periods across all four frozen response metrics."
                },
                {
                  "horizon": "5d",
                  "headline": "The broad FOMC 1d pattern does not extend into a coherent 5d effect. The 5d surface is metric-dependent, and the raw-return cell is a near-0.5 knife-edge that is highly leave-out sensitive."
                }
              ],
              "cell_states": [
                {
                  "cell_key": "FOMC|1d|raw_return",
                  "memp": "0.674559",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|1d|spy_relative_ar",
                  "memp": "0.672357",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|1d|sector_relative_ar",
                  "memp": "0.662996",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|1d|sar",
                  "memp": "0.725771",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|5d|raw_return",
                  "memp": "0.501155",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "FOMC|5d|spy_relative_ar",
                  "memp": "0.527329",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "FOMC|5d|sector_relative_ar",
                  "memp": "0.408006",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|5d|sar",
                  "memp": "0.556582",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                }
              ]
            },
            {
              "context_scope": "aggregate",
              "source": "mission_g",
              "evidence_class": "Mission G descriptive historical evidence",
              "statement": "The frame-complete FOMC lane is broadly null: no state axis holds a stable rank association with any response lens.",
              "stability": {
                "continuous_associations": 120,
                "loeo_sign_reversals": 44,
                "loyo_sign_reversals": 76,
                "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
              }
            }
          ],
          "non_inheritance_note": "aggregate labels and conclusions describe published family-level surfaces; no aggregate state is inherited by this event as an individual verdict"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "robustness_timing_transmission": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published robustness, timing, and transmission surfaces for this event's family - aggregate context with its own evidence class, never an event verdict.",
        "data": {
          "mission_g": {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": "Mission G descriptive historical evidence",
            "stability": {
              "continuous_associations": 120,
              "loeo_sign_reversals": 44,
              "loyo_sign_reversals": 76,
              "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
            },
            "fomc_null": "The frame-complete FOMC lane is broadly null: no state axis holds a stable rank association with any response lens."
          },
          "mission_j": {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": "Mission J same-sample Class B robustness (prospectively frozen post-outcome challenges)",
            "j1b_cells": [
              {
                "cell": 1,
                "measurement": "KRE",
                "lens": "rolling_beta_ar",
                "role": "balance_sheet_sensitive_second_order",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 2,
                "measurement": "IAT",
                "lens": "rolling_beta_ar",
                "role": "balance_sheet_sensitive_second_order",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 3,
                "measurement": "KBE",
                "lens": "rolling_beta_ar",
                "role": "balance_sheet_sensitive_second_order",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 4,
                "measurement": "XLF",
                "lens": "rolling_beta_ar",
                "role": "broad_financial_sector",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 5,
                "measurement": "VFH",
                "lens": "rolling_beta_ar",
                "role": "broad_financial_sector",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 6,
                "measurement": "IAT",
                "lens": "raw_return",
                "role": "balance_sheet_sensitive_second_order",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 7,
                "measurement": "KBE",
                "lens": "raw_return",
                "role": "balance_sheet_sensitive_second_order",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 8,
                "measurement": "XLF",
                "lens": "raw_return",
                "role": "broad_financial_sector",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 9,
                "measurement": "VFH",
                "lens": "raw_return",
                "role": "broad_financial_sector",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 10,
                "measurement": "2Y_CMT",
                "lens": "raw_change",
                "role": "policy_rates_repricing",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 11,
                "measurement": "2S10S_CMT",
                "lens": "raw_change",
                "role": "curve_shape_contextual_layer",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 12,
                "measurement": "SHY",
                "lens": "raw_return",
                "role": "policy_rates_repricing",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              }
            ],
            "j1b_panels": [
              {
                "role": "balance_sheet_sensitive_second_order",
                "modifier": "BROAD MEASUREMENT CONSISTENCY"
              },
              {
                "role": "broad_financial_sector",
                "modifier": "BROAD MEASUREMENT CONSISTENCY"
              },
              {
                "role": "policy_rates_repricing",
                "modifier": "BROAD MEASUREMENT CONSISTENCY"
              }
            ],
            "measurement_limited": "measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy, and the 2Y CMT blends policy expectations with term premium",
            "correlated_views_disclosure": "the frozen cells are correlated robustness views over overlapping events, assets, benchmarks, and reference structures - not independent replications and not independent statistical tests",
            "j2_timing_cells": [
              {
                "metric": "raw_return",
                "window": "[-5, -1]",
                "label": "ORDINARY_UNRESOLVED"
              },
              {
                "metric": "spy_relative_ar",
                "window": "[-5, -1]",
                "label": "ORDINARY_UNRESOLVED"
              },
              {
                "metric": "sector_relative_ar",
                "window": "[-5, -1]",
                "label": "ELEVATED"
              },
              {
                "metric": "sar",
                "window": "[-5, -1]",
                "label": "ELEVATED"
              }
            ],
            "j2_raw_cell_fragility": "the raw-return pre-event cell is knife-edge: the direction of its median-percentile reading flips under the published leave-one-out perturbations while its assigned state is unchanged",
            "c2_opec_collision_tags": "0/65",
            "c1_status": "unadjudicable",
            "c1_note": "events are described as outside known-register collisions only; no stronger clean-window claim exists, and the C1 branch above is unadjudicable in the published execution",
            "j3_edges": [
              {
                "edge": "E1",
                "from": "fomc_decision",
                "to": "policy_rates_repricing",
                "upstream_reading": "ACTIVATED",
                "upstream_path": "upstream activation definitional (all 65 anchors exist); UPSTREAM NOT ACTIVATED and DOWNSTREAM WITHOUT UPSTREAM structurally unreachable on E1 (J0 section 12.3)",
                "downstream_state": "ELEVATED",
                "downstream_m_class": "M2",
                "downstream_modifier": "BROAD MEASUREMENT CONSISTENCY",
                "route_b_satisfied": false,
                "state": "PROPAGATED",
                "rule_path": "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (usable M1/M2 primary stands alone (Route A)) -> PROPAGATED (J0 section 5)"
              },
              {
                "edge": "E2",
                "from": "policy_rates_repricing",
                "to": "balance_sheet_sensitive_second_order",
                "upstream_reading": "ACTIVATED",
                "upstream_path": "usable M2 primary at State A stands alone -> ACTIVATED (J0 section 5)",
                "downstream_state": "ELEVATED",
                "downstream_m_class": "M3",
                "downstream_modifier": "BROAD MEASUREMENT CONSISTENCY",
                "route_b_satisfied": false,
                "state": "PROPAGATED",
                "rule_path": "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)"
              },
              {
                "edge": "E3",
                "from": "balance_sheet_sensitive_second_order",
                "to": "broad_financial_sector",
                "upstream_reading": "ACTIVATED",
                "upstream_path": "M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)",
                "downstream_state": "ELEVATED",
                "downstream_m_class": "M3",
                "downstream_modifier": "BROAD MEASUREMENT CONSISTENCY",
                "route_b_satisfied": false,
                "state": "PROPAGATED",
                "rule_path": "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)"
              }
            ],
            "j3_note": "PROPAGATED is a frozen descriptive edge label at the published claim ceiling, not event-level causal transmission"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
            "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
            "bytes": 14476,
            "note": "Mission J evidence source (j1b)"
          },
          {
            "artifact": "stats/J2_TIMING_COLLISION_RESULTS.md",
            "sha256": "f51e58e3705933f53a4f3d8381ab6795e9aa5119281c73638f9b5d50a9015d97",
            "bytes": 18563,
            "note": "Mission J evidence source (j2)"
          },
          {
            "artifact": "stats/J3_MECHANISM_TRANSMISSION_READOUT.md",
            "sha256": "41e73b5cbe82dec11351bdf4d8f06c0715d4d56074e14fe275c6ba3fcbe16aef",
            "bytes": 12175,
            "note": "Mission J evidence source (j3)"
          }
        ]
      },
      "falsifier_fragility": {
        "status": "available",
        "reason_code": "published_falsifier_context",
        "summary": "Published falsifier and fragility context applicable to this event's family and cells.",
        "data": {
          "scope_note": "family-level falsifier context; no per-event falsifier outcome is assigned",
          "battery_disclosure": "Stability synthesis The six falsifiers stand separately.",
          "cell_overlays": [
            {
              "cell_key": "FOMC|1d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|1d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|1d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|1d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 5
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 32
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 1
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            }
          ],
          "knife_edge": {
            "scope": "family-level fragility context",
            "cell_key": "FOMC|5d|raw_return",
            "memp": "0.501155",
            "f1_loyo": {
              "runs": 8,
              "flips": 5
            },
            "f2_loeo": {
              "runs": 65,
              "flips": 32
            }
          }
        },
        "source_references": [
          {
            "artifact": "stats/I2C_FALSIFIERS.md",
            "sha256": "86dcf82ad4e8381695451db19d0b64f47abc9c353ed24ac1433e70857963d7d5",
            "bytes": 59232,
            "note": "Mission I falsifier battery publication"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "missingness_limitations": {
        "status": "available",
        "reason_code": "missingness_inventory",
        "summary": "Everything known to be missing, structurally unavailable, unadjudicable, or aggregate-only for this event - research outputs, not implementation defects.",
        "data": {
          "items": [
            {
              "reason_code": "computation_date_not_recorded",
              "statement": "computation dates are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "execution_commit_not_recorded",
              "statement": "execution commits are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "source_section_not_exposed",
              "statement": "no source-section field is exposed by mission-i-evidence-v2; the source artifact and hash are exposed instead"
            },
            {
              "reason_code": "aggregate_context_only",
              "statement": "robustness, timing, transmission, and falsifier surfaces are aggregate-level published context; no per-event adjudication exists"
            },
            {
              "reason_code": "scheduled_anchor_limitation",
              "statement": "anchor quality scheduled_or_weak_anchor: anticipation cannot be separated from the decision at a scheduled announcement"
            },
            {
              "reason_code": "fomc_20d_ordinary_substrate_unavailable",
              "statement": "the FOMC 20d ordinary-period comparison is structurally unavailable - not a data gap"
            },
            {
              "reason_code": "ideal_rates_measure_unavailable",
              "statement": "measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy, and the 2Y CMT blends policy expectations with term premium"
            },
            {
              "reason_code": "collision_register_unadjudicable",
              "statement": "events are described as outside known-register collisions only; no stronger clean-window claim exists, and the C1 branch above is unadjudicable in the published execution"
            },
            {
              "reason_code": "credit_source_pre_window",
              "statement": "HY OAS coverage is era-bounded by the surviving source window; pre-window FOMC events carry no credit state"
            }
          ]
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
            "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
            "bytes": 39855,
            "note": "frame-complete FOMC identity and source ledger"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
            "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
            "bytes": 14476,
            "note": "Mission J evidence source (j1b)"
          },
          {
            "artifact": "stats/J2_TIMING_COLLISION_RESULTS.md",
            "sha256": "f51e58e3705933f53a4f3d8381ab6795e9aa5119281c73638f9b5d50a9015d97",
            "bytes": 18563,
            "note": "Mission J evidence source (j2)"
          }
        ]
      },
      "evidence_class_claim_ceiling": {
        "status": "available",
        "reason_code": "published_evidence_classes",
        "summary": "The evidence classes that apply to this dossier, kept separate and never pooled - each named program cited.",
        "data": {
          "classes": [
            "Mission G descriptive historical evidence (outcome-blind frozen chain)",
            "Mission I descriptive / comparative ordinary-period evidence (frozen before any outcome comparison)",
            "Mission J same-sample Class B robustness (prospectively frozen post-outcome challenges)",
            "G6C illustration-only enrichment (published per-event dossier)"
          ],
          "pooling_prohibition": "The accepted track record and the historical ledgers are separate denominators answering different questions; they are never pooled, summed, or compared as one sample.",
          "claim_ceiling": "descriptive published evidence only; the strictest applicable published ceiling governs every reading"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
            "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
            "bytes": 14476,
            "note": "Mission J evidence source (j1b)"
          },
          {
            "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
            "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
            "bytes": 21943,
            "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
          }
        ]
      },
      "non_claim": {
        "status": "available",
        "reason_code": "permanent_non_claim",
        "summary": "The permanent non-claim carried by every dossier.",
        "data": {
          "statement": "This dossier assembles published descriptive evidence for one dated event. Aggregate labels remain aggregate context and are not individual-event classifications. The record is not a causal estimate, significance test, independent replication, prediction, trade signal or proof of a mechanism."
        },
        "source_references": [
          {
            "artifact": "event-dossier-v1",
            "note": "the dossier contract itself carries this permanent non-claim"
          }
        ]
      }
    }
  },
  "fomc_core": {
    "contract_version": "event-dossier-v1",
    "candidate_id": "fomc-policy-decision-2018-01-31",
    "top_level_status": "COMPLETE",
    "enrichment_tier": "core_published_evidence",
    "sections": {
      "identity": {
        "status": "available",
        "reason_code": "exact_slug_join",
        "summary": "Exact identity join between the family identity ledger and the Mission I event-level surface; event date and anchor session are kept separate.",
        "data": {
          "candidate_id": "fomc-policy-decision-2018-01-31",
          "family": "FOMC",
          "event_date": "2018-01-31",
          "anchor_session": "2018-01-31",
          "identity_status": "exact_join"
        },
        "source_references": [
          {
            "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
            "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
            "bytes": 39855,
            "note": "frame-complete FOMC identity and source ledger"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "source_provenance": {
        "status": "available",
        "reason_code": "tracked_ledger_row",
        "summary": "Official dated source pinned in the tracked identity ledger; the untracked local archive is never consulted.",
        "data": {
          "source_description": "Maintain target range at 1.25-1.50 percent",
          "official_source_reference": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20180131a.htm",
          "source_artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
          "source_row_key": "fomc-policy-decision-2018-01-31",
          "artifact_sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
          "anchor_quality": "scheduled_or_weak_anchor",
          "publication_timestamp": "2:00 p.m. EST",
          "schedule_status": "scheduled"
        },
        "source_references": [
          {
            "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
            "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
            "bytes": 39855,
            "note": "frame-complete FOMC identity and source ledger"
          }
        ]
      },
      "eligibility_denominators": {
        "status": "available",
        "reason_code": "mission_i_universe_lane",
        "summary": "FOMC family denominator and per-horizon ordinary reference denominators from the frozen Mission I universe funnel; the two family ledgers are never pooled.",
        "data": {
          "family_event_n": 65,
          "family_event_n_attempted": 65,
          "reference_n_by_horizon": {
            "1d": {
              "reference_n_attempted": 1816,
              "reference_n_available": 1816,
              "non_overlapping_blocks": 927,
              "status": "feasible"
            },
            "5d": {
              "reference_n_attempted": 1299,
              "reference_n_available": 1299,
              "non_overlapping_blocks": 233,
              "status": "feasible"
            },
            "20d": {
              "reference_n_attempted": 0,
              "reference_n_available": 0,
              "non_overlapping_blocks": 0,
              "status": "structurally_infeasible"
            }
          },
          "available_horizons": [
            "1d",
            "5d"
          ],
          "unavailable_horizons": [
            "20d"
          ],
          "eligibility_gate": "frozen I1 candidate-universe funnel (era, estimation, forward, gap, and exclusion cuts)"
        },
        "source_references": [
          {
            "artifact": "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
            "sha256": "b16d5863fda0541c43ff5a75dfb8e6c76a92af46f92c7971a8390f56132a9964",
            "bytes": 5073,
            "note": "Mission I candidate-universe funnel"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "mechanism_asset_basis": {
        "status": "available",
        "reason_code": "canonical_g3_family_mapping",
        "summary": "Frozen family-level transmission mapping from the tracked G3 mapping contract - family context, not a bespoke event-level causal finding.",
        "data": {
          "mechanism_hypothesis": "policy decision -> policy path / funding and curve conditions -> regional-bank equities",
          "mechanism_role": "family-level frozen mapping context; not an event-level causal finding",
          "scope": "family_level",
          "primary_asset": "KRE",
          "market_benchmark": "SPY",
          "sector_benchmark": "XLF",
          "price_basis_policy": "Raw-only sessions (adjusted basis unavailable): 0 — F3 basis is uniformly adjusted, no cross-basis pairing.",
          "claim_ceiling": "KRE is one predeclared second-order equity transmission lens for FOMC decisions. It is not the complete market reaction to monetary policy and does not imply every FOMC decision should move regional banks in one direction.",
          "mapping_version": {
            "status": "available",
            "value": "g3-transmission-map-v1",
            "source_artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md",
            "sha256": "61921026c78df980353461f808e8ff184a774614a5f24db51cdc48a20a083167",
            "bytes": 5978,
            "note": "canonical frozen family mapping (g3-transmission-map-v1)"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_observations": {
        "status": "available",
        "reason_code": "mission_i_event_level_rows",
        "summary": "Every published per-event observation for this event from the Mission I event-level surface, in publication order.",
        "data": {
          "rows": [
            {
              "horizon": "1d",
              "metric": "raw_return",
              "response": "0.014767",
              "abs_mid_rank_pct": "0.663546",
              "signed_pct": "0.821586"
            },
            {
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "response": "0.015903",
              "abs_mid_rank_pct": "0.791300",
              "signed_pct": "0.902533"
            },
            {
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "response": "0.005353",
              "abs_mid_rank_pct": "0.486784",
              "signed_pct": "0.753304"
            },
            {
              "horizon": "1d",
              "metric": "sar",
              "response": "1.584840",
              "abs_mid_rank_pct": "0.904185",
              "signed_pct": "0.953744"
            },
            {
              "horizon": "5d",
              "metric": "raw_return",
              "response": "-0.019101",
              "abs_mid_rank_pct": "0.420323",
              "signed_pct": "0.263279"
            },
            {
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "response": "0.031378",
              "abs_mid_rank_pct": "0.725943",
              "signed_pct": "0.866821"
            },
            {
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "response": "0.025620",
              "abs_mid_rank_pct": "0.787529",
              "signed_pct": "0.883757"
            },
            {
              "horizon": "5d",
              "metric": "sar",
              "response": "1.398466",
              "abs_mid_rank_pct": "0.849885",
              "signed_pct": "0.921478"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score."
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_enrichment": {
        "status": "not_exposed",
        "reason_code": "per_event_reaction_not_published",
        "summary": "No published per-event reaction dossier exists for this event; the six G6C dossiers are an enrichment tier, not a coverage requirement.",
        "data": null,
        "source_references": [
          {
            "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
            "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
            "bytes": 21943,
            "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
          }
        ]
      },
      "ordinary_period_context": {
        "status": "available",
        "reason_code": "mission_i_cells_joined",
        "summary": "This event's published observations joined to their frozen ordinary-period cells with both denominators and the published aggregates visible.",
        "data": {
          "rows": [
            {
              "cell_key": "FOMC|1d|raw_return",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "raw_return",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.674559",
              "published_signed_percentile_median": "0.339207",
              "event_response": "0.014767",
              "abs_mid_rank_pct": "0.663546",
              "signed_pct": "0.821586"
            },
            {
              "cell_key": "FOMC|1d|spy_relative_ar",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.672357",
              "published_signed_percentile_median": "0.405286",
              "event_response": "0.015903",
              "abs_mid_rank_pct": "0.791300",
              "signed_pct": "0.902533"
            },
            {
              "cell_key": "FOMC|1d|sector_relative_ar",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.662996",
              "published_signed_percentile_median": "0.386013",
              "event_response": "0.005353",
              "abs_mid_rank_pct": "0.486784",
              "signed_pct": "0.753304"
            },
            {
              "cell_key": "FOMC|1d|sar",
              "family": "FOMC",
              "horizon": "1d",
              "metric": "sar",
              "event_n": 65,
              "reference_n": 1816,
              "published_memp": "0.725771",
              "published_signed_percentile_median": "0.377753",
              "event_response": "1.584840",
              "abs_mid_rank_pct": "0.904185",
              "signed_pct": "0.953744"
            },
            {
              "cell_key": "FOMC|5d|raw_return",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "raw_return",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.501155",
              "published_signed_percentile_median": "0.447267",
              "event_response": "-0.019101",
              "abs_mid_rank_pct": "0.420323",
              "signed_pct": "0.263279"
            },
            {
              "cell_key": "FOMC|5d|spy_relative_ar",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.527329",
              "published_signed_percentile_median": "0.504234",
              "event_response": "0.031378",
              "abs_mid_rank_pct": "0.725943",
              "signed_pct": "0.866821"
            },
            {
              "cell_key": "FOMC|5d|sector_relative_ar",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.408006",
              "published_signed_percentile_median": "0.501925",
              "event_response": "0.025620",
              "abs_mid_rank_pct": "0.787529",
              "signed_pct": "0.883757"
            },
            {
              "cell_key": "FOMC|5d|sar",
              "family": "FOMC",
              "horizon": "5d",
              "metric": "sar",
              "event_n": 65,
              "reference_n": 1299,
              "published_memp": "0.556582",
              "published_signed_percentile_median": "0.505004",
              "event_response": "1.398466",
              "abs_mid_rank_pct": "0.849885",
              "signed_pct": "0.921478"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score.",
          "fomc_20d": {
            "status": "structurally_unavailable",
            "reason_code": "fomc_20d_ordinary_substrate_unavailable",
            "limitation": "The 20d horizon is structurally infeasible: with the estimation and forward gates removing nothing in-era, the exclusion geometry alone leaves zero eligible sessions — a pre-declared calendar fact (I0 §8), not a data gap and not rescued by any substitute date."
          }
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "aggregate_research_context": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published aggregate conclusions for this event's family - context for reading the event, never an individual-event label.",
        "data": {
          "contexts": [
            {
              "context_scope": "aggregate",
              "source": "mission_i",
              "evidence_class": "Mission I descriptive / comparative ordinary-period evidence",
              "family_readouts": [
                {
                  "horizon": "1d",
                  "headline": "FOMC decision windows show a broad, perturbation-stable elevation in one-day response magnitude relative to era-matched ordinary periods across all four frozen response metrics."
                },
                {
                  "horizon": "5d",
                  "headline": "The broad FOMC 1d pattern does not extend into a coherent 5d effect. The 5d surface is metric-dependent, and the raw-return cell is a near-0.5 knife-edge that is highly leave-out sensitive."
                }
              ],
              "cell_states": [
                {
                  "cell_key": "FOMC|1d|raw_return",
                  "memp": "0.674559",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|1d|spy_relative_ar",
                  "memp": "0.672357",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|1d|sector_relative_ar",
                  "memp": "0.662996",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|1d|sar",
                  "memp": "0.725771",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|5d|raw_return",
                  "memp": "0.501155",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "FOMC|5d|spy_relative_ar",
                  "memp": "0.527329",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "FOMC|5d|sector_relative_ar",
                  "memp": "0.408006",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "FOMC|5d|sar",
                  "memp": "0.556582",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                }
              ]
            },
            {
              "context_scope": "aggregate",
              "source": "mission_g",
              "evidence_class": "Mission G descriptive historical evidence",
              "statement": "The frame-complete FOMC lane is broadly null: no state axis holds a stable rank association with any response lens.",
              "stability": {
                "continuous_associations": 120,
                "loeo_sign_reversals": 44,
                "loyo_sign_reversals": 76,
                "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
              }
            }
          ],
          "non_inheritance_note": "aggregate labels and conclusions describe published family-level surfaces; no aggregate state is inherited by this event as an individual verdict"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "robustness_timing_transmission": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published robustness, timing, and transmission surfaces for this event's family - aggregate context with its own evidence class, never an event verdict.",
        "data": {
          "mission_g": {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": "Mission G descriptive historical evidence",
            "stability": {
              "continuous_associations": 120,
              "loeo_sign_reversals": 44,
              "loyo_sign_reversals": 76,
              "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
            },
            "fomc_null": "The frame-complete FOMC lane is broadly null: no state axis holds a stable rank association with any response lens."
          },
          "mission_j": {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": "Mission J same-sample Class B robustness (prospectively frozen post-outcome challenges)",
            "j1b_cells": [
              {
                "cell": 1,
                "measurement": "KRE",
                "lens": "rolling_beta_ar",
                "role": "balance_sheet_sensitive_second_order",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 2,
                "measurement": "IAT",
                "lens": "rolling_beta_ar",
                "role": "balance_sheet_sensitive_second_order",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 3,
                "measurement": "KBE",
                "lens": "rolling_beta_ar",
                "role": "balance_sheet_sensitive_second_order",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 4,
                "measurement": "XLF",
                "lens": "rolling_beta_ar",
                "role": "broad_financial_sector",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 5,
                "measurement": "VFH",
                "lens": "rolling_beta_ar",
                "role": "broad_financial_sector",
                "events": "64 / 65",
                "unavailable_events": [
                  [
                    "2018-01-31",
                    "insufficient_history_252_20"
                  ]
                ],
                "label": "ELEVATED"
              },
              {
                "cell": 6,
                "measurement": "IAT",
                "lens": "raw_return",
                "role": "balance_sheet_sensitive_second_order",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 7,
                "measurement": "KBE",
                "lens": "raw_return",
                "role": "balance_sheet_sensitive_second_order",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 8,
                "measurement": "XLF",
                "lens": "raw_return",
                "role": "broad_financial_sector",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 9,
                "measurement": "VFH",
                "lens": "raw_return",
                "role": "broad_financial_sector",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 10,
                "measurement": "2Y_CMT",
                "lens": "raw_change",
                "role": "policy_rates_repricing",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 11,
                "measurement": "2S10S_CMT",
                "lens": "raw_change",
                "role": "curve_shape_contextual_layer",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              },
              {
                "cell": 12,
                "measurement": "SHY",
                "lens": "raw_return",
                "role": "policy_rates_repricing",
                "events": "65 / 65",
                "unavailable_events": [],
                "label": "ELEVATED"
              }
            ],
            "j1b_panels": [
              {
                "role": "balance_sheet_sensitive_second_order",
                "modifier": "BROAD MEASUREMENT CONSISTENCY"
              },
              {
                "role": "broad_financial_sector",
                "modifier": "BROAD MEASUREMENT CONSISTENCY"
              },
              {
                "role": "policy_rates_repricing",
                "modifier": "BROAD MEASUREMENT CONSISTENCY"
              }
            ],
            "measurement_limited": "measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy, and the 2Y CMT blends policy expectations with term premium",
            "correlated_views_disclosure": "the frozen cells are correlated robustness views over overlapping events, assets, benchmarks, and reference structures - not independent replications and not independent statistical tests",
            "j2_timing_cells": [
              {
                "metric": "raw_return",
                "window": "[-5, -1]",
                "label": "ORDINARY_UNRESOLVED"
              },
              {
                "metric": "spy_relative_ar",
                "window": "[-5, -1]",
                "label": "ORDINARY_UNRESOLVED"
              },
              {
                "metric": "sector_relative_ar",
                "window": "[-5, -1]",
                "label": "ELEVATED"
              },
              {
                "metric": "sar",
                "window": "[-5, -1]",
                "label": "ELEVATED"
              }
            ],
            "j2_raw_cell_fragility": "the raw-return pre-event cell is knife-edge: the direction of its median-percentile reading flips under the published leave-one-out perturbations while its assigned state is unchanged",
            "c2_opec_collision_tags": "0/65",
            "c1_status": "unadjudicable",
            "c1_note": "events are described as outside known-register collisions only; no stronger clean-window claim exists, and the C1 branch above is unadjudicable in the published execution",
            "j3_edges": [
              {
                "edge": "E1",
                "from": "fomc_decision",
                "to": "policy_rates_repricing",
                "upstream_reading": "ACTIVATED",
                "upstream_path": "upstream activation definitional (all 65 anchors exist); UPSTREAM NOT ACTIVATED and DOWNSTREAM WITHOUT UPSTREAM structurally unreachable on E1 (J0 section 12.3)",
                "downstream_state": "ELEVATED",
                "downstream_m_class": "M2",
                "downstream_modifier": "BROAD MEASUREMENT CONSISTENCY",
                "route_b_satisfied": false,
                "state": "PROPAGATED",
                "rule_path": "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (usable M1/M2 primary stands alone (Route A)) -> PROPAGATED (J0 section 5)"
              },
              {
                "edge": "E2",
                "from": "policy_rates_repricing",
                "to": "balance_sheet_sensitive_second_order",
                "upstream_reading": "ACTIVATED",
                "upstream_path": "usable M2 primary at State A stands alone -> ACTIVATED (J0 section 5)",
                "downstream_state": "ELEVATED",
                "downstream_m_class": "M3",
                "downstream_modifier": "BROAD MEASUREMENT CONSISTENCY",
                "route_b_satisfied": false,
                "state": "PROPAGATED",
                "rule_path": "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)"
              },
              {
                "edge": "E3",
                "from": "balance_sheet_sensitive_second_order",
                "to": "broad_financial_sector",
                "upstream_reading": "ACTIVATED",
                "upstream_path": "M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)",
                "downstream_state": "ELEVATED",
                "downstream_m_class": "M3",
                "downstream_modifier": "BROAD MEASUREMENT CONSISTENCY",
                "route_b_satisfied": false,
                "state": "PROPAGATED",
                "rule_path": "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)"
              }
            ],
            "j3_note": "PROPAGATED is a frozen descriptive edge label at the published claim ceiling, not event-level causal transmission"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
            "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
            "bytes": 14476,
            "note": "Mission J evidence source (j1b)"
          },
          {
            "artifact": "stats/J2_TIMING_COLLISION_RESULTS.md",
            "sha256": "f51e58e3705933f53a4f3d8381ab6795e9aa5119281c73638f9b5d50a9015d97",
            "bytes": 18563,
            "note": "Mission J evidence source (j2)"
          },
          {
            "artifact": "stats/J3_MECHANISM_TRANSMISSION_READOUT.md",
            "sha256": "41e73b5cbe82dec11351bdf4d8f06c0715d4d56074e14fe275c6ba3fcbe16aef",
            "bytes": 12175,
            "note": "Mission J evidence source (j3)"
          }
        ]
      },
      "falsifier_fragility": {
        "status": "available",
        "reason_code": "published_falsifier_context",
        "summary": "Published falsifier and fragility context applicable to this event's family and cells.",
        "data": {
          "scope_note": "family-level falsifier context; no per-event falsifier outcome is assigned",
          "battery_disclosure": "Stability synthesis The six falsifiers stand separately.",
          "cell_overlays": [
            {
              "cell_key": "FOMC|1d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|1d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|1d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|1d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 5
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 32
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "FOMC|5d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 1
              },
              "f2_loeo": {
                "runs": 65,
                "flips": 0
              },
              "f3_sign_flip": false
            }
          ],
          "knife_edge": {
            "scope": "family-level fragility context",
            "cell_key": "FOMC|5d|raw_return",
            "memp": "0.501155",
            "f1_loyo": {
              "runs": 8,
              "flips": 5
            },
            "f2_loeo": {
              "runs": 65,
              "flips": 32
            }
          }
        },
        "source_references": [
          {
            "artifact": "stats/I2C_FALSIFIERS.md",
            "sha256": "86dcf82ad4e8381695451db19d0b64f47abc9c353ed24ac1433e70857963d7d5",
            "bytes": 59232,
            "note": "Mission I falsifier battery publication"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "missingness_limitations": {
        "status": "available",
        "reason_code": "missingness_inventory",
        "summary": "Everything known to be missing, structurally unavailable, unadjudicable, or aggregate-only for this event - research outputs, not implementation defects.",
        "data": {
          "items": [
            {
              "reason_code": "computation_date_not_recorded",
              "statement": "computation dates are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "execution_commit_not_recorded",
              "statement": "execution commits are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "source_section_not_exposed",
              "statement": "no source-section field is exposed by mission-i-evidence-v2; the source artifact and hash are exposed instead"
            },
            {
              "reason_code": "aggregate_context_only",
              "statement": "robustness, timing, transmission, and falsifier surfaces are aggregate-level published context; no per-event adjudication exists"
            },
            {
              "reason_code": "scheduled_anchor_limitation",
              "statement": "anchor quality scheduled_or_weak_anchor: anticipation cannot be separated from the decision at a scheduled announcement"
            },
            {
              "reason_code": "fomc_20d_ordinary_substrate_unavailable",
              "statement": "the FOMC 20d ordinary-period comparison is structurally unavailable - not a data gap"
            },
            {
              "reason_code": "ideal_rates_measure_unavailable",
              "statement": "measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy, and the 2Y CMT blends policy expectations with term premium"
            },
            {
              "reason_code": "collision_register_unadjudicable",
              "statement": "events are described as outside known-register collisions only; no stronger clean-window claim exists, and the C1 branch above is unadjudicable in the published execution"
            },
            {
              "reason_code": "credit_source_pre_window",
              "statement": "HY OAS coverage is era-bounded by the surviving source window; pre-window FOMC events carry no credit state"
            }
          ]
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G1A_FOMC_FRAME_INVENTORY.md",
            "sha256": "59966d911222a275d3cb82b87c0b5c3c289066104ea4cad2884c92d4aeab8ada",
            "bytes": 39855,
            "note": "frame-complete FOMC identity and source ledger"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
            "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
            "bytes": 14476,
            "note": "Mission J evidence source (j1b)"
          },
          {
            "artifact": "stats/J2_TIMING_COLLISION_RESULTS.md",
            "sha256": "f51e58e3705933f53a4f3d8381ab6795e9aa5119281c73638f9b5d50a9015d97",
            "bytes": 18563,
            "note": "Mission J evidence source (j2)"
          }
        ]
      },
      "evidence_class_claim_ceiling": {
        "status": "available",
        "reason_code": "published_evidence_classes",
        "summary": "The evidence classes that apply to this dossier, kept separate and never pooled - each named program cited.",
        "data": {
          "classes": [
            "Mission G descriptive historical evidence (outcome-blind frozen chain)",
            "Mission I descriptive / comparative ordinary-period evidence (frozen before any outcome comparison)",
            "Mission J same-sample Class B robustness (prospectively frozen post-outcome challenges)"
          ],
          "pooling_prohibition": "The accepted track record and the historical ledgers are separate denominators answering different questions; they are never pooled, summed, or compared as one sample.",
          "claim_ceiling": "descriptive published evidence only; the strictest applicable published ceiling governs every reading"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
            "sha256": "c82c259b1cddd4af596c169f8a10f5d85f5292dcc9085fbf4756578bcdb81f88",
            "bytes": 14476,
            "note": "Mission J evidence source (j1b)"
          }
        ]
      },
      "non_claim": {
        "status": "available",
        "reason_code": "permanent_non_claim",
        "summary": "The permanent non-claim carried by every dossier.",
        "data": {
          "statement": "This dossier assembles published descriptive evidence for one dated event. Aggregate labels remain aggregate context and are not individual-event classifications. The record is not a causal estimate, significance test, independent replication, prediction, trade signal or proof of a mechanism."
        },
        "source_references": [
          {
            "artifact": "event-dossier-v1",
            "note": "the dossier contract itself carries this permanent non-claim"
          }
        ]
      }
    }
  },
  "opec_enriched": {
    "contract_version": "event-dossier-v1",
    "candidate_id": "opec-2023-11-30-voluntary-2p2",
    "top_level_status": "COMPLETE",
    "enrichment_tier": "published_per_event_dossier",
    "sections": {
      "identity": {
        "status": "available",
        "reason_code": "exact_slug_join",
        "summary": "Exact identity join between the family identity ledger and the Mission I event-level surface; event date and anchor session are kept separate.",
        "data": {
          "candidate_id": "opec-2023-11-30-voluntary-2p2",
          "family": "OPEC",
          "event_date": "2023-11-30",
          "anchor_session": "2023-11-30",
          "identity_status": "exact_join"
        },
        "source_references": [
          {
            "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
            "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
            "bytes": 20695,
            "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "source_provenance": {
        "status": "available",
        "reason_code": "tracked_ledger_row",
        "summary": "Official dated source pinned in the tracked identity ledger; the untracked local archive is never consulted.",
        "data": {
          "source_description": "Coordinated additional voluntary adjustments of about 2.2 mb/d for Q1 2024",
          "official_source_reference": "36th ONOMM PR + coordinating-producers statement",
          "source_artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
          "source_row_key": "opec-2023-11-30-voluntary-2p2",
          "artifact_sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
          "anchor_quality": "pinned_official / scheduled",
          "ledger_key": "D23",
          "action_type": "reduction (coordinated voluntary)"
        },
        "source_references": [
          {
            "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
            "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
            "bytes": 20695,
            "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
          }
        ]
      },
      "eligibility_denominators": {
        "status": "available",
        "reason_code": "mission_i_universe_lane",
        "summary": "OPEC family denominator and per-horizon ordinary reference denominators from the frozen Mission I universe funnel; the two family ledgers are never pooled.",
        "data": {
          "family_event_n": 32,
          "family_event_n_attempted": 32,
          "reference_n_by_horizon": {
            "1d": {
              "reference_n_attempted": 1903,
              "reference_n_available": 1903,
              "non_overlapping_blocks": 960,
              "status": "feasible"
            },
            "5d": {
              "reference_n_attempted": 1631,
              "reference_n_available": 1631,
              "non_overlapping_blocks": 287,
              "status": "feasible"
            },
            "20d": {
              "reference_n_attempted": 889,
              "reference_n_available": 889,
              "non_overlapping_blocks": 51,
              "status": "feasible"
            }
          },
          "available_horizons": [
            "1d",
            "5d",
            "20d"
          ],
          "unavailable_horizons": [],
          "eligibility_gate": "frozen I1 candidate-universe funnel (era, estimation, forward, gap, and exclusion cuts)"
        },
        "source_references": [
          {
            "artifact": "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
            "sha256": "b16d5863fda0541c43ff5a75dfb8e6c76a92af46f92c7971a8390f56132a9964",
            "bytes": 5073,
            "note": "Mission I candidate-universe funnel"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "mechanism_asset_basis": {
        "status": "available",
        "reason_code": "canonical_g3_family_mapping",
        "summary": "Frozen family-level transmission mapping from the tracked G3 mapping contract - family context, not a bespoke event-level causal finding.",
        "data": {
          "mechanism_hypothesis": "collective production policy -> crude supply expectations -> producer cash flows -> exploration-and-production equities",
          "mechanism_role": "family-level frozen mapping context; not an event-level causal finding",
          "scope": "family_level",
          "primary_asset": "XOP",
          "market_benchmark": "SPY",
          "sector_benchmark": "XLE",
          "price_basis_policy": "Raw-only sessions (adjusted basis unavailable): 0 — F3 basis is uniformly adjusted, no cross-basis pairing.",
          "claim_ceiling": "XOP is one predeclared producer-equity transmission lens for collective OPEC/OPEC+ production policy. It is not a complete measure of oil-market consequences.",
          "mapping_version": {
            "status": "available",
            "value": "g3-transmission-map-v1",
            "source_artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md",
            "sha256": "61921026c78df980353461f808e8ff184a774614a5f24db51cdc48a20a083167",
            "bytes": 5978,
            "note": "canonical frozen family mapping (g3-transmission-map-v1)"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_observations": {
        "status": "available",
        "reason_code": "mission_i_event_level_rows",
        "summary": "Every published per-event observation for this event from the Mission I event-level surface, in publication order.",
        "data": {
          "rows": [
            {
              "horizon": "1d",
              "metric": "raw_return",
              "response": "0.007971",
              "abs_mid_rank_pct": "0.318970",
              "signed_pct": "0.652128"
            },
            {
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "response": "0.002055",
              "abs_mid_rank_pct": "0.097740",
              "signed_pct": "0.567525"
            },
            {
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "response": "0.002769",
              "abs_mid_rank_pct": "0.250657",
              "signed_pct": "0.647399"
            },
            {
              "horizon": "1d",
              "metric": "sar",
              "response": "0.130394",
              "abs_mid_rank_pct": "0.113505",
              "signed_pct": "0.574882"
            },
            {
              "horizon": "5d",
              "metric": "raw_return",
              "response": "-0.052753",
              "abs_mid_rank_pct": "0.746168",
              "signed_pct": "0.125077"
            },
            {
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "response": "-0.056763",
              "abs_mid_rank_pct": "0.814224",
              "signed_pct": "0.092581"
            },
            {
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "response": "-0.014565",
              "abs_mid_rank_pct": "0.576947",
              "signed_pct": "0.231147"
            },
            {
              "horizon": "5d",
              "metric": "sar",
              "response": "-1.610604",
              "abs_mid_rank_pct": "0.894543",
              "signed_pct": "0.056407"
            },
            {
              "horizon": "20d",
              "metric": "raw_return",
              "response": "-0.000322",
              "abs_mid_rank_pct": "0.004499",
              "signed_pct": "0.479190"
            },
            {
              "horizon": "20d",
              "metric": "spy_relative_ar",
              "response": "-0.045977",
              "abs_mid_rank_pct": "0.341957",
              "signed_pct": "0.358830"
            },
            {
              "horizon": "20d",
              "metric": "sector_relative_ar",
              "response": "-0.001093",
              "abs_mid_rank_pct": "0.020247",
              "signed_pct": "0.517435"
            },
            {
              "horizon": "20d",
              "metric": "sar",
              "response": "-0.652281",
              "abs_mid_rank_pct": "0.391451",
              "signed_pct": "0.332958"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score."
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_enrichment": {
        "status": "available",
        "reason_code": "g6c_published_per_event_dossier",
        "summary": "Published G6C per-event dossier: four-lens 1d/5d/20d readout and role wording - illustration-only enrichment, never proof and never a universe.",
        "data": {
          "readout_rows": [
            {
              "metric": "absolute asset return",
              "1d": "+0.80%",
              "5d": "-5.28%",
              "20d": "-0.03%"
            },
            {
              "metric": "SPY-relative AR",
              "1d": "+0.21%",
              "5d": "-5.68%",
              "20d": "-4.60%"
            },
            {
              "metric": "sector-relative AR",
              "1d": "+0.28%",
              "5d": "-1.46%",
              "20d": "-0.11%"
            },
            {
              "metric": "SAR",
              "1d": "+0.13",
              "5d": "-1.61",
              "20d": "-0.65"
            }
          ],
          "role_in_record": "illustrates stable descriptive association (with unresolved calendar-time confounding).",
          "source_description": "Coordinated additional voluntary adjustments of about 2.2 mb/d for Q1 2024",
          "source_ledger_reference": "36th ONOMM PR + coordinating-producers statement"
        },
        "source_references": [
          {
            "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
            "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
            "bytes": 21943,
            "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
          }
        ]
      },
      "ordinary_period_context": {
        "status": "available",
        "reason_code": "mission_i_cells_joined",
        "summary": "This event's published observations joined to their frozen ordinary-period cells with both denominators and the published aggregates visible.",
        "data": {
          "rows": [
            {
              "cell_key": "OPEC|1d|raw_return",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "raw_return",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.529164",
              "published_signed_percentile_median": "0.406463",
              "event_response": "0.007971",
              "abs_mid_rank_pct": "0.318970",
              "signed_pct": "0.652128"
            },
            {
              "cell_key": "OPEC|1d|spy_relative_ar",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.523384",
              "published_signed_percentile_median": "0.493431",
              "event_response": "0.002055",
              "abs_mid_rank_pct": "0.097740",
              "signed_pct": "0.567525"
            },
            {
              "cell_key": "OPEC|1d|sector_relative_ar",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.472149",
              "published_signed_percentile_median": "0.461377",
              "event_response": "0.002769",
              "abs_mid_rank_pct": "0.250657",
              "signed_pct": "0.647399"
            },
            {
              "cell_key": "OPEC|1d|sar",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "sar",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.602733",
              "published_signed_percentile_median": "0.492643",
              "event_response": "0.130394",
              "abs_mid_rank_pct": "0.113505",
              "signed_pct": "0.574882"
            },
            {
              "cell_key": "OPEC|5d|raw_return",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "raw_return",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.469957",
              "published_signed_percentile_median": "0.597180",
              "event_response": "-0.052753",
              "abs_mid_rank_pct": "0.746168",
              "signed_pct": "0.125077"
            },
            {
              "cell_key": "OPEC|5d|spy_relative_ar",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.584304",
              "published_signed_percentile_median": "0.625996",
              "event_response": "-0.056763",
              "abs_mid_rank_pct": "0.814224",
              "signed_pct": "0.092581"
            },
            {
              "cell_key": "OPEC|5d|sector_relative_ar",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.428878",
              "published_signed_percentile_median": "0.565604",
              "event_response": "-0.014565",
              "abs_mid_rank_pct": "0.576947",
              "signed_pct": "0.231147"
            },
            {
              "cell_key": "OPEC|5d|sar",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "sar",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.580012",
              "published_signed_percentile_median": "0.639485",
              "event_response": "-1.610604",
              "abs_mid_rank_pct": "0.894543",
              "signed_pct": "0.056407"
            },
            {
              "cell_key": "OPEC|20d|raw_return",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "raw_return",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.420135",
              "published_signed_percentile_median": "0.553431",
              "event_response": "-0.000322",
              "abs_mid_rank_pct": "0.004499",
              "signed_pct": "0.479190"
            },
            {
              "cell_key": "OPEC|20d|spy_relative_ar",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "spy_relative_ar",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.402137",
              "published_signed_percentile_median": "0.547807",
              "event_response": "-0.045977",
              "abs_mid_rank_pct": "0.341957",
              "signed_pct": "0.358830"
            },
            {
              "cell_key": "OPEC|20d|sector_relative_ar",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "sector_relative_ar",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.449381",
              "published_signed_percentile_median": "0.539370",
              "event_response": "-0.001093",
              "abs_mid_rank_pct": "0.020247",
              "signed_pct": "0.517435"
            },
            {
              "cell_key": "OPEC|20d|sar",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "sar",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.383577",
              "published_signed_percentile_median": "0.544432",
              "event_response": "-0.652281",
              "abs_mid_rank_pct": "0.391451",
              "signed_pct": "0.332958"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score."
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "aggregate_research_context": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published aggregate conclusions for this event's family - context for reading the event, never an individual-event label.",
        "data": {
          "contexts": [
            {
              "context_scope": "aggregate",
              "source": "mission_i",
              "evidence_class": "Mission I descriptive / comparative ordinary-period evidence",
              "family_readouts": [
                {
                  "horizon": "1d",
                  "headline": "OPEC 1d windows do not show a uniform cross-metric response-magnitude pattern."
                },
                {
                  "horizon": "5d",
                  "headline": "OPEC 5d results are explicitly metric-dependent and do not support a single event-exceptionality claim."
                },
                {
                  "horizon": "20d",
                  "headline": "At 20d, all four OPEC response metrics are descriptively lower in magnitude than their ordinary-period references. The direction survives the frozen leave-out and overlap perturbations, but the result is not a universal cross-horizon mechanism because three of four metrics change direction across feasible horizons."
                }
              ],
              "cell_states": [
                {
                  "cell_key": "OPEC|1d|raw_return",
                  "memp": "0.529164",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|1d|spy_relative_ar",
                  "memp": "0.523384",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|1d|sector_relative_ar",
                  "memp": "0.472149",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|1d|sar",
                  "memp": "0.602733",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|5d|raw_return",
                  "memp": "0.469957",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|5d|spy_relative_ar",
                  "memp": "0.584304",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|5d|sector_relative_ar",
                  "memp": "0.428878",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|5d|sar",
                  "memp": "0.580012",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|20d|raw_return",
                  "memp": "0.420135",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|20d|spy_relative_ar",
                  "memp": "0.402137",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|20d|sector_relative_ar",
                  "memp": "0.449381",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|20d|sar",
                  "memp": "0.383577",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "outside"
                }
              ]
            },
            {
              "context_scope": "aggregate",
              "source": "mission_g",
              "evidence_class": "Mission G descriptive historical evidence",
              "statement": "stable descriptive association with unresolved calendar-time confounding",
              "confound_note": "the state axis itself tracks calendar time inside this lane, so these data cannot separate state from era",
              "stability": {
                "continuous_associations": 120,
                "loeo_sign_reversals": 44,
                "loyo_sign_reversals": 76,
                "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
              }
            }
          ],
          "non_inheritance_note": "aggregate labels and conclusions describe published family-level surfaces; no aggregate state is inherited by this event as an individual verdict"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "robustness_timing_transmission": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published robustness, timing, and transmission surfaces for this event's family - aggregate context with its own evidence class, never an event verdict.",
        "data": {
          "mission_g": {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": "Mission G descriptive historical evidence",
            "stability": {
              "continuous_associations": 120,
              "loeo_sign_reversals": 44,
              "loyo_sign_reversals": 76,
              "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
            },
            "bounded_association": "stable descriptive association with unresolved calendar-time confounding",
            "credit_limitation": {
              "available": 36,
              "of": 97,
              "fomc_subset": 20,
              "opec_subset": 16,
              "era_bounded": true,
              "status": "secondary",
              "fragile_associations": 9,
              "of_associations": 12,
              "note": "HY OAS history before the surviving source window is source-withdrawn; the subset is descriptive only and was not promoted after outcomes were visible"
            }
          },
          "mission_j": {
            "status": "not_applicable",
            "reason_code": "mission_j_fomc_only",
            "context_scope": "aggregate",
            "note": "Mission J challenges the inherited FOMC one-day reading over the 65-event FOMC frame only; no OPEC robustness surface exists in Mission J"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "falsifier_fragility": {
        "status": "available",
        "reason_code": "published_falsifier_context",
        "summary": "Published falsifier and fragility context applicable to this event's family and cells.",
        "data": {
          "scope_note": "family-level falsifier context; no per-event falsifier outcome is assigned",
          "battery_disclosure": "Stability synthesis The six falsifiers stand separately.",
          "cell_overlays": [
            {
              "cell_key": "OPEC|1d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 1
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|1d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 2
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|1d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|1d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 1
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            }
          ],
          "era_bounded_credit": {
            "available": 36,
            "of": 97,
            "fomc_subset": 20,
            "opec_subset": 16,
            "era_bounded": true,
            "status": "secondary",
            "fragile_associations": 9,
            "of_associations": 12,
            "note": "HY OAS history before the surviving source window is source-withdrawn; the subset is descriptive only and was not promoted after outcomes were visible"
          },
          "calendar_time_confound": "the state axis itself tracks calendar time inside this lane, so these data cannot separate state from era"
        },
        "source_references": [
          {
            "artifact": "stats/I2C_FALSIFIERS.md",
            "sha256": "86dcf82ad4e8381695451db19d0b64f47abc9c353ed24ac1433e70857963d7d5",
            "bytes": 59232,
            "note": "Mission I falsifier battery publication"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "missingness_limitations": {
        "status": "available",
        "reason_code": "missingness_inventory",
        "summary": "Everything known to be missing, structurally unavailable, unadjudicable, or aggregate-only for this event - research outputs, not implementation defects.",
        "data": {
          "items": [
            {
              "reason_code": "computation_date_not_recorded",
              "statement": "computation dates are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "execution_commit_not_recorded",
              "statement": "execution commits are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "source_section_not_exposed",
              "statement": "no source-section field is exposed by mission-i-evidence-v2; the source artifact and hash are exposed instead"
            },
            {
              "reason_code": "aggregate_context_only",
              "statement": "robustness, timing, transmission, and falsifier surfaces are aggregate-level published context; no per-event adjudication exists"
            },
            {
              "reason_code": "scheduled_anchor_limitation",
              "statement": "anchor quality pinned_official / scheduled: anticipation cannot be separated from the decision at a scheduled announcement"
            },
            {
              "reason_code": "credit_source_pre_window",
              "statement": "the OPEC credit lens is era-bounded and secondary-only; pre-window events carry no credit state"
            },
            {
              "reason_code": "mission_j_fomc_only",
              "statement": "no Mission J robustness surface exists for OPEC events"
            }
          ]
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
            "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
            "bytes": 20695,
            "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "evidence_class_claim_ceiling": {
        "status": "available",
        "reason_code": "published_evidence_classes",
        "summary": "The evidence classes that apply to this dossier, kept separate and never pooled - each named program cited.",
        "data": {
          "classes": [
            "Mission G descriptive historical evidence (outcome-blind frozen chain)",
            "Mission I descriptive / comparative ordinary-period evidence (frozen before any outcome comparison)",
            "G6C illustration-only enrichment (published per-event dossier)"
          ],
          "pooling_prohibition": "The accepted track record and the historical ledgers are separate denominators answering different questions; they are never pooled, summed, or compared as one sample.",
          "claim_ceiling": "descriptive published evidence only; the strictest applicable published ceiling governs every reading"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          },
          {
            "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
            "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
            "bytes": 21943,
            "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
          }
        ]
      },
      "non_claim": {
        "status": "available",
        "reason_code": "permanent_non_claim",
        "summary": "The permanent non-claim carried by every dossier.",
        "data": {
          "statement": "This dossier assembles published descriptive evidence for one dated event. Aggregate labels remain aggregate context and are not individual-event classifications. The record is not a causal estimate, significance test, independent replication, prediction, trade signal or proof of a mechanism."
        },
        "source_references": [
          {
            "artifact": "event-dossier-v1",
            "note": "the dossier contract itself carries this permanent non-claim"
          }
        ]
      }
    }
  },
  "opec_core": {
    "contract_version": "event-dossier-v1",
    "candidate_id": "opec-2018-06-23-conformity-return",
    "top_level_status": "COMPLETE",
    "enrichment_tier": "core_published_evidence",
    "sections": {
      "identity": {
        "status": "available",
        "reason_code": "exact_slug_join",
        "summary": "Exact identity join between the family identity ledger and the Mission I event-level surface; event date and anchor session are kept separate.",
        "data": {
          "candidate_id": "opec-2018-06-23-conformity-return",
          "family": "OPEC",
          "event_date": "2018-06-23",
          "anchor_session": "2018-06-22",
          "identity_status": "exact_join"
        },
        "source_references": [
          {
            "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
            "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
            "bytes": 20695,
            "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "source_provenance": {
        "status": "available",
        "reason_code": "tracked_ledger_row",
        "summary": "Official dated source pinned in the tracked identity ledger; the untracked local archive is never consulted.",
        "data": {
          "source_description": "OPEC+ returns to 100 percent conformity (about 1 mb/d effective supply increase)",
          "official_source_reference": "4th ONOMM PR",
          "source_artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
          "source_row_key": "opec-2018-06-23-conformity-return",
          "artifact_sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
          "anchor_quality": "pinned_official / scheduled",
          "ledger_key": "D02",
          "action_type": "increase (effective)"
        },
        "source_references": [
          {
            "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
            "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
            "bytes": 20695,
            "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
          }
        ]
      },
      "eligibility_denominators": {
        "status": "available",
        "reason_code": "mission_i_universe_lane",
        "summary": "OPEC family denominator and per-horizon ordinary reference denominators from the frozen Mission I universe funnel; the two family ledgers are never pooled.",
        "data": {
          "family_event_n": 32,
          "family_event_n_attempted": 32,
          "reference_n_by_horizon": {
            "1d": {
              "reference_n_attempted": 1903,
              "reference_n_available": 1903,
              "non_overlapping_blocks": 960,
              "status": "feasible"
            },
            "5d": {
              "reference_n_attempted": 1631,
              "reference_n_available": 1631,
              "non_overlapping_blocks": 287,
              "status": "feasible"
            },
            "20d": {
              "reference_n_attempted": 889,
              "reference_n_available": 889,
              "non_overlapping_blocks": 51,
              "status": "feasible"
            }
          },
          "available_horizons": [
            "1d",
            "5d",
            "20d"
          ],
          "unavailable_horizons": [],
          "eligibility_gate": "frozen I1 candidate-universe funnel (era, estimation, forward, gap, and exclusion cuts)"
        },
        "source_references": [
          {
            "artifact": "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
            "sha256": "b16d5863fda0541c43ff5a75dfb8e6c76a92af46f92c7971a8390f56132a9964",
            "bytes": 5073,
            "note": "Mission I candidate-universe funnel"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "mechanism_asset_basis": {
        "status": "available",
        "reason_code": "canonical_g3_family_mapping",
        "summary": "Frozen family-level transmission mapping from the tracked G3 mapping contract - family context, not a bespoke event-level causal finding.",
        "data": {
          "mechanism_hypothesis": "collective production policy -> crude supply expectations -> producer cash flows -> exploration-and-production equities",
          "mechanism_role": "family-level frozen mapping context; not an event-level causal finding",
          "scope": "family_level",
          "primary_asset": "XOP",
          "market_benchmark": "SPY",
          "sector_benchmark": "XLE",
          "price_basis_policy": "Raw-only sessions (adjusted basis unavailable): 0 — F3 basis is uniformly adjusted, no cross-basis pairing.",
          "claim_ceiling": "XOP is one predeclared producer-equity transmission lens for collective OPEC/OPEC+ production policy. It is not a complete measure of oil-market consequences.",
          "mapping_version": {
            "status": "available",
            "value": "g3-transmission-map-v1",
            "source_artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANICAL_ELIGIBILITY.md",
            "sha256": "61921026c78df980353461f808e8ff184a774614a5f24db51cdc48a20a083167",
            "bytes": 5978,
            "note": "canonical frozen family mapping (g3-transmission-map-v1)"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_observations": {
        "status": "available",
        "reason_code": "mission_i_event_level_rows",
        "summary": "Every published per-event observation for this event from the Mission I event-level surface, in publication order.",
        "data": {
          "rows": [
            {
              "horizon": "1d",
              "metric": "raw_return",
              "response": "-0.026297",
              "abs_mid_rank_pct": "0.776668",
              "signed_pct": "0.109301"
            },
            {
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "response": "-0.012684",
              "abs_mid_rank_pct": "0.529164",
              "signed_pct": "0.237520"
            },
            {
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "response": "-0.006204",
              "abs_mid_rank_pct": "0.528114",
              "signed_pct": "0.240673"
            },
            {
              "horizon": "1d",
              "metric": "sar",
              "response": "-0.817273",
              "abs_mid_rank_pct": "0.615870",
              "signed_pct": "0.196006"
            },
            {
              "horizon": "5d",
              "metric": "raw_return",
              "response": "0.011035",
              "abs_mid_rank_pct": "0.215205",
              "signed_pct": "0.580012"
            },
            {
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "response": "0.023629",
              "abs_mid_rank_pct": "0.424893",
              "signed_pct": "0.733906"
            },
            {
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "response": "0.000523",
              "abs_mid_rank_pct": "0.022685",
              "signed_pct": "0.521153"
            },
            {
              "horizon": "5d",
              "metric": "sar",
              "response": "0.680869",
              "abs_mid_rank_pct": "0.509503",
              "signed_pct": "0.768853"
            },
            {
              "horizon": "20d",
              "metric": "raw_return",
              "response": "-0.006809",
              "abs_mid_rank_pct": "0.058493",
              "signed_pct": "0.457818"
            },
            {
              "horizon": "20d",
              "metric": "spy_relative_ar",
              "response": "-0.026683",
              "abs_mid_rank_pct": "0.188976",
              "signed_pct": "0.451069"
            },
            {
              "horizon": "20d",
              "metric": "sector_relative_ar",
              "response": "0.001042",
              "abs_mid_rank_pct": "0.019123",
              "signed_pct": "0.537683"
            },
            {
              "horizon": "20d",
              "metric": "sar",
              "response": "-0.384424",
              "abs_mid_rank_pct": "0.226097",
              "signed_pct": "0.427447"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score."
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "reaction_enrichment": {
        "status": "not_exposed",
        "reason_code": "per_event_reaction_not_published",
        "summary": "No published per-event reaction dossier exists for this event; the six G6C dossiers are an enrichment tier, not a coverage requirement.",
        "data": null,
        "source_references": [
          {
            "artifact": "stats/G6C_REPRESENTATIVE_CASES.md",
            "sha256": "e0ffdf7580cb59e1d7a19a8d5e8513f65b5a63a8ac8e6837d6f3b1a0d739488b",
            "bytes": 21943,
            "note": "published per-event dossiers (enrichment tier only - never a universal core source)"
          }
        ]
      },
      "ordinary_period_context": {
        "status": "available",
        "reason_code": "mission_i_cells_joined",
        "summary": "This event's published observations joined to their frozen ordinary-period cells with both denominators and the published aggregates visible.",
        "data": {
          "rows": [
            {
              "cell_key": "OPEC|1d|raw_return",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "raw_return",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.529164",
              "published_signed_percentile_median": "0.406463",
              "event_response": "-0.026297",
              "abs_mid_rank_pct": "0.776668",
              "signed_pct": "0.109301"
            },
            {
              "cell_key": "OPEC|1d|spy_relative_ar",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "spy_relative_ar",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.523384",
              "published_signed_percentile_median": "0.493431",
              "event_response": "-0.012684",
              "abs_mid_rank_pct": "0.529164",
              "signed_pct": "0.237520"
            },
            {
              "cell_key": "OPEC|1d|sector_relative_ar",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "sector_relative_ar",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.472149",
              "published_signed_percentile_median": "0.461377",
              "event_response": "-0.006204",
              "abs_mid_rank_pct": "0.528114",
              "signed_pct": "0.240673"
            },
            {
              "cell_key": "OPEC|1d|sar",
              "family": "OPEC",
              "horizon": "1d",
              "metric": "sar",
              "event_n": 32,
              "reference_n": 1903,
              "published_memp": "0.602733",
              "published_signed_percentile_median": "0.492643",
              "event_response": "-0.817273",
              "abs_mid_rank_pct": "0.615870",
              "signed_pct": "0.196006"
            },
            {
              "cell_key": "OPEC|5d|raw_return",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "raw_return",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.469957",
              "published_signed_percentile_median": "0.597180",
              "event_response": "0.011035",
              "abs_mid_rank_pct": "0.215205",
              "signed_pct": "0.580012"
            },
            {
              "cell_key": "OPEC|5d|spy_relative_ar",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "spy_relative_ar",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.584304",
              "published_signed_percentile_median": "0.625996",
              "event_response": "0.023629",
              "abs_mid_rank_pct": "0.424893",
              "signed_pct": "0.733906"
            },
            {
              "cell_key": "OPEC|5d|sector_relative_ar",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "sector_relative_ar",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.428878",
              "published_signed_percentile_median": "0.565604",
              "event_response": "0.000523",
              "abs_mid_rank_pct": "0.022685",
              "signed_pct": "0.521153"
            },
            {
              "cell_key": "OPEC|5d|sar",
              "family": "OPEC",
              "horizon": "5d",
              "metric": "sar",
              "event_n": 32,
              "reference_n": 1631,
              "published_memp": "0.580012",
              "published_signed_percentile_median": "0.639485",
              "event_response": "0.680869",
              "abs_mid_rank_pct": "0.509503",
              "signed_pct": "0.768853"
            },
            {
              "cell_key": "OPEC|20d|raw_return",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "raw_return",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.420135",
              "published_signed_percentile_median": "0.553431",
              "event_response": "-0.006809",
              "abs_mid_rank_pct": "0.058493",
              "signed_pct": "0.457818"
            },
            {
              "cell_key": "OPEC|20d|spy_relative_ar",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "spy_relative_ar",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.402137",
              "published_signed_percentile_median": "0.547807",
              "event_response": "-0.026683",
              "abs_mid_rank_pct": "0.188976",
              "signed_pct": "0.451069"
            },
            {
              "cell_key": "OPEC|20d|sector_relative_ar",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "sector_relative_ar",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.449381",
              "published_signed_percentile_median": "0.539370",
              "event_response": "0.001042",
              "abs_mid_rank_pct": "0.019123",
              "signed_pct": "0.537683"
            },
            {
              "cell_key": "OPEC|20d|sar",
              "family": "OPEC",
              "horizon": "20d",
              "metric": "sar",
              "event_n": 32,
              "reference_n": 889,
              "published_memp": "0.383577",
              "published_signed_percentile_median": "0.544432",
              "event_response": "-0.384424",
              "abs_mid_rank_pct": "0.226097",
              "signed_pct": "0.427447"
            }
          ],
          "method_note": "Never ordered by percentile, response magnitude, or MEMP contribution. abs_mid_rank_pct is the published mid-rank method percentile, not a strength, rank, or probability score."
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          }
        ]
      },
      "aggregate_research_context": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published aggregate conclusions for this event's family - context for reading the event, never an individual-event label.",
        "data": {
          "contexts": [
            {
              "context_scope": "aggregate",
              "source": "mission_i",
              "evidence_class": "Mission I descriptive / comparative ordinary-period evidence",
              "family_readouts": [
                {
                  "horizon": "1d",
                  "headline": "OPEC 1d windows do not show a uniform cross-metric response-magnitude pattern."
                },
                {
                  "horizon": "5d",
                  "headline": "OPEC 5d results are explicitly metric-dependent and do not support a single event-exceptionality claim."
                },
                {
                  "horizon": "20d",
                  "headline": "At 20d, all four OPEC response metrics are descriptively lower in magnitude than their ordinary-period references. The direction survives the frozen leave-out and overlap perturbations, but the result is not a universal cross-horizon mechanism because three of four metrics change direction across feasible horizons."
                }
              ],
              "cell_states": [
                {
                  "cell_key": "OPEC|1d|raw_return",
                  "memp": "0.529164",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|1d|spy_relative_ar",
                  "memp": "0.523384",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|1d|sector_relative_ar",
                  "memp": "0.472149",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|1d|sar",
                  "memp": "0.602733",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|5d|raw_return",
                  "memp": "0.469957",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|5d|spy_relative_ar",
                  "memp": "0.584304",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|5d|sector_relative_ar",
                  "memp": "0.428878",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|5d|sar",
                  "memp": "0.580012",
                  "memp_direction": "above_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|20d|raw_return",
                  "memp": "0.420135",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|20d|spy_relative_ar",
                  "memp": "0.402137",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "inside"
                },
                {
                  "cell_key": "OPEC|20d|sector_relative_ar",
                  "memp": "0.449381",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "outside"
                },
                {
                  "cell_key": "OPEC|20d|sar",
                  "memp": "0.383577",
                  "memp_direction": "below_ordinary_midpoint",
                  "f6_position": "outside"
                }
              ]
            },
            {
              "context_scope": "aggregate",
              "source": "mission_g",
              "evidence_class": "Mission G descriptive historical evidence",
              "statement": "stable descriptive association with unresolved calendar-time confounding",
              "confound_note": "the state axis itself tracks calendar time inside this lane, so these data cannot separate state from era",
              "stability": {
                "continuous_associations": 120,
                "loeo_sign_reversals": 44,
                "loyo_sign_reversals": 76,
                "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
              }
            }
          ],
          "non_inheritance_note": "aggregate labels and conclusions describe published family-level surfaces; no aggregate state is inherited by this event as an individual verdict"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "robustness_timing_transmission": {
        "status": "available",
        "reason_code": "aggregate_context_only",
        "summary": "Published robustness, timing, and transmission surfaces for this event's family - aggregate context with its own evidence class, never an event verdict.",
        "data": {
          "mission_g": {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": "Mission G descriptive historical evidence",
            "stability": {
              "continuous_associations": 120,
              "loeo_sign_reversals": 44,
              "loyo_sign_reversals": 76,
              "note": "leave-one-event-out and leave-one-calendar-year-out diagnostics were applied uniformly to every association; surviving them is not validation"
            },
            "bounded_association": "stable descriptive association with unresolved calendar-time confounding",
            "credit_limitation": {
              "available": 36,
              "of": 97,
              "fomc_subset": 20,
              "opec_subset": 16,
              "era_bounded": true,
              "status": "secondary",
              "fragile_associations": 9,
              "of_associations": 12,
              "note": "HY OAS history before the surviving source window is source-withdrawn; the subset is descriptive only and was not promoted after outcomes were visible"
            }
          },
          "mission_j": {
            "status": "not_applicable",
            "reason_code": "mission_j_fomc_only",
            "context_scope": "aggregate",
            "note": "Mission J challenges the inherited FOMC one-day reading over the 65-event FOMC frame only; no OPEC robustness surface exists in Mission J"
          }
        },
        "source_references": [
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "falsifier_fragility": {
        "status": "available",
        "reason_code": "published_falsifier_context",
        "summary": "Published falsifier and fragility context applicable to this event's family and cells.",
        "data": {
          "scope_note": "family-level falsifier context; no per-event falsifier outcome is assigned",
          "battery_disclosure": "Stability synthesis The six falsifiers stand separately.",
          "cell_overlays": [
            {
              "cell_key": "OPEC|1d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 1
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|1d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 2
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|1d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|1d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 1
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|5d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|raw_return",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|spy_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|sector_relative_ar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            },
            {
              "cell_key": "OPEC|20d|sar",
              "f1_loyo": {
                "runs": 8,
                "flips": 0
              },
              "f2_loeo": {
                "runs": 32,
                "flips": 0
              },
              "f3_sign_flip": false
            }
          ],
          "era_bounded_credit": {
            "available": 36,
            "of": 97,
            "fomc_subset": 20,
            "opec_subset": 16,
            "era_bounded": true,
            "status": "secondary",
            "fragile_associations": 9,
            "of_associations": 12,
            "note": "HY OAS history before the surviving source window is source-withdrawn; the subset is descriptive only and was not promoted after outcomes were visible"
          },
          "calendar_time_confound": "the state axis itself tracks calendar time inside this lane, so these data cannot separate state from era"
        },
        "source_references": [
          {
            "artifact": "stats/I2C_FALSIFIERS.md",
            "sha256": "86dcf82ad4e8381695451db19d0b64f47abc9c353ed24ac1433e70857963d7d5",
            "bytes": 59232,
            "note": "Mission I falsifier battery publication"
          },
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "missingness_limitations": {
        "status": "available",
        "reason_code": "missingness_inventory",
        "summary": "Everything known to be missing, structurally unavailable, unadjudicable, or aggregate-only for this event - research outputs, not implementation defects.",
        "data": {
          "items": [
            {
              "reason_code": "computation_date_not_recorded",
              "statement": "computation dates are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "execution_commit_not_recorded",
              "statement": "execution commits are recorded in no Mission I publication and are stated null, never inferred"
            },
            {
              "reason_code": "source_section_not_exposed",
              "statement": "no source-section field is exposed by mission-i-evidence-v2; the source artifact and hash are exposed instead"
            },
            {
              "reason_code": "aggregate_context_only",
              "statement": "robustness, timing, transmission, and falsifier surfaces are aggregate-level published context; no per-event adjudication exists"
            },
            {
              "reason_code": "scheduled_anchor_limitation",
              "statement": "anchor quality pinned_official / scheduled: anticipation cannot be separated from the decision at a scheduled announcement"
            },
            {
              "reason_code": "credit_source_pre_window",
              "statement": "the OPEC credit lens is era-bounded and secondary-only; pre-window events carry no credit state"
            },
            {
              "reason_code": "mission_j_fomc_only",
              "statement": "no Mission J robustness surface exists for OPEC events"
            }
          ]
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G1B_OPEC_DESIGNED_RESERVOIR.md",
            "sha256": "acde4aa06a1f60ae67071aac94b0166d4142ffb58c524cda7edd35827e00de1d",
            "bytes": 20695,
            "note": "OPEC designed-reservoir identity and source ledger (32 canonical reservoir-ready identities)"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "evidence_class_claim_ceiling": {
        "status": "available",
        "reason_code": "published_evidence_classes",
        "summary": "The evidence classes that apply to this dossier, kept separate and never pooled - each named program cited.",
        "data": {
          "classes": [
            "Mission G descriptive historical evidence (outcome-blind frozen chain)",
            "Mission I descriptive / comparative ordinary-period evidence (frozen before any outcome comparison)"
          ],
          "pooling_prohibition": "The accepted track record and the historical ledgers are separate denominators answering different questions; they are never pooled, summed, or compared as one sample.",
          "claim_ceiling": "descriptive published evidence only; the strictest applicable published ceiling governs every reading"
        },
        "source_references": [
          {
            "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
            "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
            "bytes": 101773,
            "note": "Mission I event-level surface via mission-i-evidence-v2"
          },
          {
            "artifact": "stats/G3_MECHANISM_CLASSIFICATION_ATTRITION.md",
            "sha256": "73c1b97974d8b058fcc8624f92ba16df4d208cce0199add130cd83b7a2a818c4",
            "bytes": 6584,
            "note": "Mission G evidence source (mechanism_attrition)"
          },
          {
            "artifact": "stats/G5_PROMOTION_PROOF.md",
            "sha256": "b707ec177ac15dce66f8c6b1335ccb4905826780ad017b22f57203a659d6b1d1",
            "bytes": 9188,
            "note": "Mission G evidence source (promotion_proof)"
          },
          {
            "artifact": "stats/G6_FROZEN_MANIFEST_READOUT.md",
            "sha256": "fa50b8e9a1999a2d9bfdb10950e7e68f854af6cb64bb2fcd6450610531aa0b1b",
            "bytes": 39790,
            "note": "Mission G evidence source (readout)"
          },
          {
            "artifact": "stats/G6B_STABILITY_AND_FALSIFIERS.md",
            "sha256": "8cb81ac0a49c282f0c0c9ba03e83e70976d93afdf918990f2178f58e308a0f5c",
            "bytes": 46080,
            "note": "Mission G evidence source (stability)"
          }
        ]
      },
      "non_claim": {
        "status": "available",
        "reason_code": "permanent_non_claim",
        "summary": "The permanent non-claim carried by every dossier.",
        "data": {
          "statement": "This dossier assembles published descriptive evidence for one dated event. Aggregate labels remain aggregate context and are not individual-event classifications. The record is not a causal estimate, significance test, independent replication, prediction, trade signal or proof of a mechanism."
        },
        "source_references": [
          {
            "artifact": "event-dossier-v1",
            "note": "the dossier contract itself carries this permanent non-claim"
          }
        ]
      }
    }
  }
};
