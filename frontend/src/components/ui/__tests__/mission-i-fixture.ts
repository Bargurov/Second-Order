/**
 * Contract-shaped Mission I fixture (mirrors GET /evidence/mission-i, the
 * N1 contract, mission-i-evidence-v1).  A typed transcription of the live
 * tracked-publication payload captured from the N1 backend builder — no
 * value below was hand-retyped, and no research value is recomputed here.
 * Not a test file — imported by the Mission I card, Evidence Overview,
 * research-record memo, and reader-guide suites.
 */
import type { MissionIEvidenceSummary } from "@/lib/api";

/** Fresh deep copy per call so sentinel-mutation tests never leak. */
export function missionIFixture(): MissionIEvidenceSummary {
  return structuredClone(MISSION_I_FIXTURE);
}

const MISSION_I_FIXTURE: MissionIEvidenceSummary = {
  "contract_version": "mission-i-evidence-v1",
  "provenance": {
    "sources": {
      "i0_protocol": {
        "artifact": "stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md",
        "sha256": "386e87afa4b4951356bc17cf1161b577689098f8b7181365f0edfb6b4c0c443a",
        "bytes": 32046
      },
      "i1_universe": {
        "artifact": "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
        "sha256": "b16d5863fda0541c43ff5a75dfb8e6c76a92af46f92c7971a8390f56132a9964",
        "bytes": 5073
      },
      "i2a_substrate": {
        "artifact": "stats/I2A_RESPONSE_SUBSTRATE.md",
        "sha256": "a3805dbf62e5be5b76b464886ded1ecaeb2f4c5ba73c7e737878d05fb32e9ae9",
        "bytes": 5326
      },
      "i2b_memp": {
        "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
        "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
        "bytes": 101773
      },
      "i2c_calibration": {
        "artifact": "stats/I2C_CALIBRATION.md",
        "sha256": "ae232878a616811dd93cd1236e2720cb93c8cd00cc21ae78a507248994218623",
        "bytes": 4795
      },
      "i2c_falsifiers": {
        "artifact": "stats/I2C_FALSIFIERS.md",
        "sha256": "86dcf82ad4e8381695451db19d0b64f47abc9c353ed24ac1433e70857963d7d5",
        "bytes": 59232
      },
      "closeout": {
        "artifact": "stats/MISSION_I_CLOSEOUT.md",
        "sha256": "09b7d9c7aee36b62f6b8238fd8d353f8df0c63da2ff642b7a4b8bcc29214f315",
        "bytes": 12867
      }
    },
    "publication_versions": {
      "i0_protocol": "i0-v1",
      "i1_universe": "i1-candidate-universe-v1",
      "i2a_substrate": "i2a-response-substrate-v1",
      "i2b_memp": "i2b-memp-primary-v1",
      "i2c_calibration": "i2c-calibration-v1",
      "i2c_falsifiers": "i2c-falsifiers-v1"
    },
    "publication_chain": "I0 protocol -> I1 candidate universe -> I2A symmetric response substrate -> I2B frozen MEMP family -> I2C-A era-matched calibration -> I2C-B falsifier battery -> closeout",
    "no_recompute_statement": "This endpoint exposes published results and computes no research statistic: no percentile, no median, no calibration, no placement draw, and no falsifier perturbation; repeated copies across publications are reconciled, never re-derived.",
    "reproduction": {
      "commands": [
        "python -m scripts.i2a_response_substrate --emit",
        "python -m unittest tests.test_i2a_response_substrate"
      ],
      "reproducibility_limits": "Full fresh-clone execution is therefore not claimed.",
      "source": "stats/I2A_RESPONSE_SUBSTRATE.md"
    },
    "computation_dates": null,
    "execution_commits": null
  },
  "constitution": {
    "protocol_version": "i0-v1",
    "frozen_question": "Are the completed Mission G event windows unusual relative to eligible ordinary non-event periods on the same frozen assets, response metrics, horizons, and calculation rules?",
    "estimand": {
      "name": "MEMP",
      "definition": "- The primary statistic is MEMP(F, m, h): the median across F's events of the magnitude percentile. Under ordinariness, MEMP is approximately 0.5; MEMP near 1 means typical event-window magnitudes sit high inside the ordinary magnitude distribution.",
      "ordinary_reference_midpoint": "0.5"
    },
    "evidence_class": {
      "descriptive": true,
      "comparative": true,
      "frozen_before_outcome_comparison": true
    },
    "primary_cell_count": 20,
    "family_pooling_prohibition": "the two families keep entirely separate ledgers; their denominators, exclusion sets, and funnels are never pooled",
    "signed_percentile_disclosure": {
      "status": "subordinate descriptive context",
      "disclaimers": [
        "the signed-percentile medians were not among the 20 calibrated primary statistics;",
        "they were not separately placement-calibrated;",
        "they are descriptive context only.",
        "The signed diagnostic does not overturn the absolute-response MEMP conclusions above and is not read as a directional or net-return statement."
      ]
    }
  },
  "universe": {
    "families": [
      {
        "family": "FOMC",
        "primary": "KRE",
        "market_benchmark": "SPY",
        "sector_benchmark": "XLF",
        "study_event_n_attempted": 65,
        "study_event_n_available": 65,
        "joint_sessions": 2385,
        "era_sessions": 2011,
        "price_basis_policy": "- Raw-only sessions (adjusted basis unavailable): 0 — F3 basis is uniformly adjusted, no cross-basis pairing.",
        "horizons": [
          {
            "horizon": "1d",
            "funnel": {
              "era": 2011,
              "estimation_cut": 0,
              "forward_cut": 0,
              "gap_cut": 0,
              "exclusion_cut": 195
            },
            "reference_n_attempted": 1816,
            "reference_n_available": 1816,
            "non_overlapping_reference_n": 927,
            "status": "feasible",
            "limitation": null
          },
          {
            "horizon": "5d",
            "funnel": {
              "era": 2011,
              "estimation_cut": 0,
              "forward_cut": 0,
              "gap_cut": 0,
              "exclusion_cut": 712
            },
            "reference_n_attempted": 1299,
            "reference_n_available": 1299,
            "non_overlapping_reference_n": 233,
            "status": "feasible",
            "limitation": null
          },
          {
            "horizon": "20d",
            "funnel": {
              "era": 2011,
              "estimation_cut": 0,
              "forward_cut": 0,
              "gap_cut": 0,
              "exclusion_cut": 2011
            },
            "reference_n_attempted": 0,
            "reference_n_available": 0,
            "non_overlapping_reference_n": 0,
            "status": "structurally_infeasible",
            "limitation": "The 20d horizon is structurally infeasible: with the estimation and forward gates removing nothing in-era, the exclusion geometry alone leaves zero eligible sessions — a pre-declared calendar fact (I0 §8), not a data gap and not rescued by any substitute date."
          }
        ],
        "exclusion": {
          "description": "- Exclusion set: the complete 65-event frame → 65 anchor sessions."
        }
      },
      {
        "family": "OPEC",
        "primary": "XOP",
        "market_benchmark": "SPY",
        "sector_benchmark": "XLE",
        "study_event_n_attempted": 32,
        "study_event_n_available": 32,
        "joint_sessions": 2385,
        "era_sessions": 2011,
        "price_basis_policy": "- Raw-only sessions (adjusted basis unavailable): 0 — F3 basis is uniformly adjusted, no cross-basis pairing.",
        "horizons": [
          {
            "horizon": "1d",
            "funnel": {
              "era": 2011,
              "estimation_cut": 0,
              "forward_cut": 0,
              "gap_cut": 0,
              "exclusion_cut": 108
            },
            "reference_n_attempted": 1903,
            "reference_n_available": 1903,
            "non_overlapping_reference_n": 960,
            "status": "feasible",
            "limitation": null
          },
          {
            "horizon": "5d",
            "funnel": {
              "era": 2011,
              "estimation_cut": 0,
              "forward_cut": 0,
              "gap_cut": 0,
              "exclusion_cut": 380
            },
            "reference_n_attempted": 1631,
            "reference_n_available": 1631,
            "non_overlapping_reference_n": 287,
            "status": "feasible",
            "limitation": null
          },
          {
            "horizon": "20d",
            "funnel": {
              "era": 2011,
              "estimation_cut": 0,
              "forward_cut": 0,
              "gap_cut": 0,
              "exclusion_cut": 1122
            },
            "reference_n_attempted": 889,
            "reference_n_available": 889,
            "non_overlapping_reference_n": 51,
            "status": "feasible",
            "limitation": null
          }
        ],
        "exclusion": {
          "register": {
            "name": "opec-known-date-exclusion-register@i0-v1",
            "calendar_dates": 41,
            "anchor_sessions": 39,
            "note": "The register is a contamination-control set."
          }
        }
      }
    ],
    "blocks_note": "It is not `eligible // h` (which ignores index positions and, at `h=1`, returns the full count), and not an independent, effective, or degrees-of-freedom sample size."
  },
  "primary_cells": [
    {
      "cell": 1,
      "cell_key": "FOMC|1d|raw_return",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "raw_return",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1816,
      "reference_n_available": 1816,
      "memp": "0.674559",
      "signed_percentile_median": "0.339207",
      "calibration_percentile": "0.997000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1816,
        "canonical_reference_n": 927,
        "decimated_memp": "0.666667",
        "change": "-0.007893",
        "sign_flip": false
      }
    },
    {
      "cell": 2,
      "cell_key": "FOMC|1d|spy_relative_ar",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "spy_relative_ar",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1816,
      "reference_n_available": 1816,
      "memp": "0.672357",
      "signed_percentile_median": "0.405286",
      "calibration_percentile": "0.999500",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1816,
        "canonical_reference_n": 927,
        "decimated_memp": "0.664509",
        "change": "-0.007848",
        "sign_flip": false
      }
    },
    {
      "cell": 3,
      "cell_key": "FOMC|1d|sector_relative_ar",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "sector_relative_ar",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1816,
      "reference_n_available": 1816,
      "memp": "0.662996",
      "signed_percentile_median": "0.386013",
      "calibration_percentile": "0.997000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1816,
        "canonical_reference_n": 927,
        "decimated_memp": "0.662352",
        "change": "-0.000644",
        "sign_flip": false
      }
    },
    {
      "cell": 4,
      "cell_key": "FOMC|1d|sar",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "sar",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1816,
      "reference_n_available": 1816,
      "memp": "0.725771",
      "signed_percentile_median": "0.377753",
      "calibration_percentile": "1.000000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1816,
        "canonical_reference_n": 927,
        "decimated_memp": "0.707659",
        "change": "-0.018112",
        "sign_flip": false
      }
    },
    {
      "cell": 5,
      "cell_key": "FOMC|5d|raw_return",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "raw_return",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1299,
      "reference_n_available": 1299,
      "memp": "0.501155",
      "signed_percentile_median": "0.447267",
      "calibration_percentile": "0.476500",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 5
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 32
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1299,
        "canonical_reference_n": 233,
        "decimated_memp": "0.506438",
        "change": "+0.005283",
        "sign_flip": false
      }
    },
    {
      "cell": 6,
      "cell_key": "FOMC|5d|spy_relative_ar",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "spy_relative_ar",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1299,
      "reference_n_available": 1299,
      "memp": "0.527329",
      "signed_percentile_median": "0.504234",
      "calibration_percentile": "0.661000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1299,
        "canonical_reference_n": 233,
        "decimated_memp": "0.506438",
        "change": "-0.020891",
        "sign_flip": false
      }
    },
    {
      "cell": 7,
      "cell_key": "FOMC|5d|sector_relative_ar",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "sector_relative_ar",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1299,
      "reference_n_available": 1299,
      "memp": "0.408006",
      "signed_percentile_median": "0.501925",
      "calibration_percentile": "0.059500",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1299,
        "canonical_reference_n": 233,
        "decimated_memp": "0.412017",
        "change": "+0.004011",
        "sign_flip": false
      }
    },
    {
      "cell": 8,
      "cell_key": "FOMC|5d|sar",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "sar",
      "event_n_attempted": 65,
      "event_n_available": 65,
      "reference_n_attempted": 1299,
      "reference_n_available": 1299,
      "memp": "0.556582",
      "signed_percentile_median": "0.505004",
      "calibration_percentile": "0.824000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 1
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1299,
        "canonical_reference_n": 233,
        "decimated_memp": "0.557940",
        "change": "+0.001358",
        "sign_flip": false
      }
    },
    {
      "cell": 9,
      "cell_key": "OPEC|1d|raw_return",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "raw_return",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1903,
      "reference_n_available": 1903,
      "memp": "0.529164",
      "signed_percentile_median": "0.406463",
      "calibration_percentile": "0.792000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 1
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1903,
        "canonical_reference_n": 960,
        "decimated_memp": "0.522917",
        "change": "-0.006248",
        "sign_flip": false
      }
    },
    {
      "cell": 10,
      "cell_key": "OPEC|1d|spy_relative_ar",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "spy_relative_ar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1903,
      "reference_n_available": 1903,
      "memp": "0.523384",
      "signed_percentile_median": "0.493431",
      "calibration_percentile": "0.705250",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 2
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1903,
        "canonical_reference_n": 960,
        "decimated_memp": "0.507292",
        "change": "-0.016092",
        "sign_flip": false
      }
    },
    {
      "cell": 11,
      "cell_key": "OPEC|1d|sector_relative_ar",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "sector_relative_ar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1903,
      "reference_n_available": 1903,
      "memp": "0.472149",
      "signed_percentile_median": "0.461377",
      "calibration_percentile": "0.550250",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1903,
        "canonical_reference_n": 960,
        "decimated_memp": "0.461979",
        "change": "-0.010170",
        "sign_flip": false
      }
    },
    {
      "cell": 12,
      "cell_key": "OPEC|1d|sar",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "sar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1903,
      "reference_n_available": 1903,
      "memp": "0.602733",
      "signed_percentile_median": "0.492643",
      "calibration_percentile": "0.885250",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1903,
        "canonical_reference_n": 960,
        "decimated_memp": "0.570833",
        "change": "-0.031899",
        "sign_flip": false
      }
    },
    {
      "cell": 13,
      "cell_key": "OPEC|5d|raw_return",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "raw_return",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1631,
      "reference_n_available": 1631,
      "memp": "0.469957",
      "signed_percentile_median": "0.597180",
      "calibration_percentile": "0.461500",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1631,
        "canonical_reference_n": 287,
        "decimated_memp": "0.445993",
        "change": "-0.023964",
        "sign_flip": false
      }
    },
    {
      "cell": 14,
      "cell_key": "OPEC|5d|spy_relative_ar",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "spy_relative_ar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1631,
      "reference_n_available": 1631,
      "memp": "0.584304",
      "signed_percentile_median": "0.625996",
      "calibration_percentile": "0.891250",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1631,
        "canonical_reference_n": 287,
        "decimated_memp": "0.588850",
        "change": "+0.004546",
        "sign_flip": false
      }
    },
    {
      "cell": 15,
      "cell_key": "OPEC|5d|sector_relative_ar",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "sector_relative_ar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1631,
      "reference_n_available": 1631,
      "memp": "0.428878",
      "signed_percentile_median": "0.565604",
      "calibration_percentile": "0.390250",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 1
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1631,
        "canonical_reference_n": 287,
        "decimated_memp": "0.372822",
        "change": "-0.056056",
        "sign_flip": false
      }
    },
    {
      "cell": 16,
      "cell_key": "OPEC|5d|sar",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "sar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 1631,
      "reference_n_available": 1631,
      "memp": "0.580012",
      "signed_percentile_median": "0.639485",
      "calibration_percentile": "0.740000",
      "state": {
        "memp_direction": "above_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 1631,
        "canonical_reference_n": 287,
        "decimated_memp": "0.585366",
        "change": "+0.005354",
        "sign_flip": false
      }
    },
    {
      "cell": 17,
      "cell_key": "OPEC|20d|raw_return",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "raw_return",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 889,
      "reference_n_available": 889,
      "memp": "0.420135",
      "signed_percentile_median": "0.553431",
      "calibration_percentile": "0.530500",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 889,
        "canonical_reference_n": 51,
        "decimated_memp": "0.450980",
        "change": "+0.030845",
        "sign_flip": false
      }
    },
    {
      "cell": 18,
      "cell_key": "OPEC|20d|spy_relative_ar",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "spy_relative_ar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 889,
      "reference_n_available": 889,
      "memp": "0.402137",
      "signed_percentile_median": "0.547807",
      "calibration_percentile": "0.297000",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "inside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 889,
        "canonical_reference_n": 51,
        "decimated_memp": "0.490196",
        "change": "+0.088059",
        "sign_flip": false
      }
    },
    {
      "cell": 19,
      "cell_key": "OPEC|20d|sector_relative_ar",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "sector_relative_ar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 889,
      "reference_n_available": 889,
      "memp": "0.449381",
      "signed_percentile_median": "0.539370",
      "calibration_percentile": "0.034500",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 889,
        "canonical_reference_n": 51,
        "decimated_memp": "0.450980",
        "change": "+0.001599",
        "sign_flip": false
      }
    },
    {
      "cell": 20,
      "cell_key": "OPEC|20d|sar",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "sar",
      "event_n_attempted": 32,
      "event_n_available": 32,
      "reference_n_attempted": 889,
      "reference_n_available": 889,
      "memp": "0.383577",
      "signed_percentile_median": "0.544432",
      "calibration_percentile": "0.049500",
      "state": {
        "memp_direction": "below_ordinary_midpoint",
        "f6_position": "outside"
      },
      "f1_loyo": {
        "runs": 8,
        "flips": 0
      },
      "f2_loeo": {
        "runs": 32,
        "flips": 0
      },
      "f3_overlap_decimation": {
        "original_reference_n": 889,
        "canonical_reference_n": 51,
        "decimated_memp": "0.431373",
        "change": "+0.047795",
        "sign_flip": false
      }
    }
  ],
  "calibration": {
    "placements_per_group": 2000,
    "seed": 20180101,
    "groups": [
      {
        "family": "FOMC",
        "horizon": "1d",
        "expected_placements": 2000,
        "completed_placements": 2000,
        "per_year_event_counts": {
          "2018": 8,
          "2019": 8,
          "2020": 9,
          "2021": 8,
          "2022": 8,
          "2023": 8,
          "2024": 8,
          "2025": 8
        }
      },
      {
        "family": "FOMC",
        "horizon": "5d",
        "expected_placements": 2000,
        "completed_placements": 2000,
        "per_year_event_counts": {
          "2018": 8,
          "2019": 8,
          "2020": 9,
          "2021": 8,
          "2022": 8,
          "2023": 8,
          "2024": 8,
          "2025": 8
        }
      },
      {
        "family": "OPEC",
        "horizon": "1d",
        "expected_placements": 2000,
        "completed_placements": 2000,
        "per_year_event_counts": {
          "2018": 2,
          "2019": 2,
          "2020": 3,
          "2021": 3,
          "2022": 4,
          "2023": 3,
          "2024": 5,
          "2025": 10
        }
      },
      {
        "family": "OPEC",
        "horizon": "5d",
        "expected_placements": 2000,
        "completed_placements": 2000,
        "per_year_event_counts": {
          "2018": 2,
          "2019": 2,
          "2020": 3,
          "2021": 3,
          "2022": 4,
          "2023": 3,
          "2024": 5,
          "2025": 10
        }
      },
      {
        "family": "OPEC",
        "horizon": "20d",
        "expected_placements": 2000,
        "completed_placements": 2000,
        "per_year_event_counts": {
          "2018": 2,
          "2019": 2,
          "2020": 3,
          "2021": 3,
          "2022": 4,
          "2023": 3,
          "2024": 5,
          "2025": 10
        }
      }
    ],
    "method": "One placement reproduces the family's per-year event count on the anchor-session year and draws, per year, that many distinct sessions uniformly without replacement from the horizon's eligible ordinary pool. The same drawn calendar feeds all four metrics. Each placement's pseudo-MEMP is the identical section-13 pipeline: each drawn session's absolute response is given its mid-rank percentile within the cell's fixed ordinary reference (self-included, per section 13's fixed-R definition), and the placement MEMP is the median across the drawn sessions. The observed MEMP's calibration percentile is its mid-rank position within the 2,000 placement MEMPs, denominator 2,000, observed external. Selection uses one local deterministic RNG seeded at 20180101, consumed in the fixed order family, horizon, placement, year.",
    "no_failure_statement": "## Placement reconciliation | family | horizon | expected placements | completed | per-year event counts (anchor-session year) | |---|---|---|---|---| | FOMC | 1d | 2000 | 2000 | 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8 | | FOMC | 5d | 2000 | 2000 | 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8 | | OPEC | 1d | 2000 | 2000 | 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:3, 2024:5, 2025:10 | | OPEC | 5d | 2000 | 2000 | 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:3, 2024:5, 2025:10 | | OPEC | 20d | 2000 | 2000 | 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:3, 2024:5, 2025:10 | Every placement reproduces the family's per-year event-count vector exactly, drawn without replacement from that year's eligible ordinary sessions for the horizon; every year's pool supplies its required count (no failure, no replacement).",
    "interpretation_ceiling": "The output is a percentile-of-placements only: no p-values, no significance threshold, no confidence interval, and no new FDR pool (the accepted-86 and Mission G pools stay separate)."
  },
  "falsifiers": {
    "definitions": {
      "f1": "F1 leave-one-year-out: recompute each MEMP excluding each calendar year's events and ordinary dates; report min/max and whether sign(MEMP - 0.5) flips (flip conventions as in G6B; no new threshold).",
      "f2": "F2 leave-one-event-out: same, removing one event at a time.",
      "f3": "F3 overlap decimation: recompute each MEMP against the deterministic non-overlapping reference subset - the canonical greedy earliest-first disjoint-window subset defined in section 9 (index-based, starts >= h+1 apart), NOT a rank-based every-h-th thinning (see the section 20 erratum); report the change and any sign flip.",
      "f4": "F4 cross-metric consistency: per family x horizon, count metrics agreeing on sign(MEMP - 0.5).",
      "f5": "F5 cross-horizon consistency: per family x metric, whether feasible horizons agree on sign(MEMP - 0.5).",
      "f6": "F6 calibration position: whether the observed MEMP falls inside the central 50 percent of its calibration distribution."
    },
    "battery_disclosure": "Stability synthesis The six falsifiers stand separately.",
    "f1_loyo": {
      "runs_total": 160,
      "flips_total": 10,
      "affected_cells": [
        {
          "cell_key": "FOMC|5d|raw_return",
          "flips": 5,
          "of": 8
        },
        {
          "cell_key": "FOMC|5d|sar",
          "flips": 1,
          "of": 8
        },
        {
          "cell_key": "OPEC|1d|raw_return",
          "flips": 1,
          "of": 8
        },
        {
          "cell_key": "OPEC|1d|spy_relative_ar",
          "flips": 2,
          "of": 8
        },
        {
          "cell_key": "OPEC|5d|sector_relative_ar",
          "flips": 1,
          "of": 8
        }
      ]
    },
    "f2_loeo": {
      "runs_total": 904,
      "flips_total": 32,
      "affected_cells": [
        {
          "cell_key": "FOMC|5d|raw_return",
          "flips": 32,
          "of": 65
        }
      ],
      "knife_edge_explanation": "The LOEO fragility is concentrated in the cell whose full-sample MEMP is almost exactly 0.5 (`0.501155`): with the family median sitting on the knife-edge, removing any single event that tips the median across 0.5 flips the sign, so a majority of leave-outs flip while the rest of the surface is leave-out stable."
    },
    "f3_overlap_decimation": {
      "sign_flips": 0,
      "of_cells": 20,
      "reading": "The direction of no primary cell depends on replacing the full overlapping ordinary reference with the canonical disjoint-window subset.",
      "limitation": "This is a dependence check on the reference construction, not an independence proof — it says nothing about whether the events themselves are independent."
    },
    "f4_cross_metric": [
      {
        "family": "FOMC",
        "horizon": "1d",
        "signs": {
          "raw_return": 1,
          "spy_relative_ar": 1,
          "sector_relative_ar": 1,
          "sar": 1
        },
        "positive": 4,
        "zero": 0,
        "negative": 0
      },
      {
        "family": "FOMC",
        "horizon": "5d",
        "signs": {
          "raw_return": 1,
          "spy_relative_ar": 1,
          "sector_relative_ar": -1,
          "sar": 1
        },
        "positive": 3,
        "zero": 0,
        "negative": 1
      },
      {
        "family": "OPEC",
        "horizon": "1d",
        "signs": {
          "raw_return": 1,
          "spy_relative_ar": 1,
          "sector_relative_ar": -1,
          "sar": 1
        },
        "positive": 3,
        "zero": 0,
        "negative": 1
      },
      {
        "family": "OPEC",
        "horizon": "5d",
        "signs": {
          "raw_return": -1,
          "spy_relative_ar": 1,
          "sector_relative_ar": -1,
          "sar": 1
        },
        "positive": 2,
        "zero": 0,
        "negative": 2
      },
      {
        "family": "OPEC",
        "horizon": "20d",
        "signs": {
          "raw_return": -1,
          "spy_relative_ar": -1,
          "sector_relative_ar": -1,
          "sar": -1
        },
        "positive": 0,
        "zero": 0,
        "negative": 4
      }
    ],
    "f5_cross_horizon": [
      {
        "family": "FOMC",
        "metric": "raw_return",
        "signs": {
          "1d": 1,
          "5d": 1,
          "20d": null
        },
        "agree": true,
        "caveat": "Cross-surface synthesis ### F4 — cross-metric direction (per family × horizon) | family × horizon | positive | zero | negative | |---|---|---|---| | FOMC 1d | 4 | 0 | 0 | | FOMC 5d | 3 | 0 | 1 | | OPEC 1d | 3 | 0 | 1 | | OPEC 5d | 2 | 0 | 2 | | OPEC 20d | 0 | 0 | 4 | ### F5 — cross-horizon consistency (per family × metric) | family | metric | feasible-horizon agreement | |---|---|---| | FOMC | raw_return | agree (see caveat) | | FOMC | SPY-relative AR | agree | | FOMC | sector-relative AR | disagree | | FOMC | SAR | agree | | OPEC | raw_return | disagree | | OPEC | SPY-relative AR | disagree | | OPEC | sector-relative AR | agree | | OPEC | SAR | disagree | Caveat on FOMC raw-return \"agree\": formal sign agreement here is weak evidence, because the 5d raw cell is the documented near-0.5 knife-edge (`MEMP = 0.501155`, LOEO `32/65`)."
      },
      {
        "family": "FOMC",
        "metric": "spy_relative_ar",
        "signs": {
          "1d": 1,
          "5d": 1,
          "20d": null
        },
        "agree": true,
        "caveat": null
      },
      {
        "family": "FOMC",
        "metric": "sector_relative_ar",
        "signs": {
          "1d": 1,
          "5d": -1,
          "20d": null
        },
        "agree": false,
        "caveat": null
      },
      {
        "family": "FOMC",
        "metric": "sar",
        "signs": {
          "1d": 1,
          "5d": 1,
          "20d": null
        },
        "agree": true,
        "caveat": null
      },
      {
        "family": "OPEC",
        "metric": "raw_return",
        "signs": {
          "1d": 1,
          "5d": -1,
          "20d": -1
        },
        "agree": false,
        "caveat": null
      },
      {
        "family": "OPEC",
        "metric": "spy_relative_ar",
        "signs": {
          "1d": 1,
          "5d": 1,
          "20d": -1
        },
        "agree": false,
        "caveat": null
      },
      {
        "family": "OPEC",
        "metric": "sector_relative_ar",
        "signs": {
          "1d": -1,
          "5d": -1,
          "20d": -1
        },
        "agree": true,
        "caveat": null
      },
      {
        "family": "OPEC",
        "metric": "sar",
        "signs": {
          "1d": 1,
          "5d": 1,
          "20d": -1
        },
        "agree": false,
        "caveat": null
      }
    ],
    "f6_calibration_position": {
      "inside": 9,
      "outside": 11,
      "outside_upper": 8,
      "outside_lower": 3,
      "limitation": "F6 is a calibration-position diagnostic, not a significance test. ## 6."
    }
  },
  "family_horizon_readout": [
    {
      "family": "FOMC",
      "horizon": "1d",
      "headline": "FOMC decision windows show a broad, perturbation-stable elevation in one-day response magnitude relative to era-matched ordinary periods across all four frozen response metrics."
    },
    {
      "family": "FOMC",
      "horizon": "5d",
      "headline": "The broad FOMC 1d pattern does not extend into a coherent 5d effect. The 5d surface is metric-dependent, and the raw-return cell is a near-0.5 knife-edge that is highly leave-out sensitive."
    },
    {
      "family": "OPEC",
      "horizon": "1d",
      "headline": "OPEC 1d windows do not show a uniform cross-metric response-magnitude pattern."
    },
    {
      "family": "OPEC",
      "horizon": "5d",
      "headline": "OPEC 5d results are explicitly metric-dependent and do not support a single event-exceptionality claim."
    },
    {
      "family": "OPEC",
      "horizon": "20d",
      "headline": "At 20d, all four OPEC response metrics are descriptively lower in magnitude than their ordinary-period references. The direction survives the frozen leave-out and overlap perturbations, but the result is not a universal cross-horizon mechanism because three of four metrics change direction across feasible horizons."
    }
  ],
  "fragility": {
    "knife_edge": {
      "cell_key": "FOMC|5d|raw_return",
      "memp": "0.501155",
      "calibration_percentile": "0.476500",
      "f1_loyo": {
        "runs": 8,
        "flips": 5
      },
      "f2_loeo": {
        "runs": 65,
        "flips": 32
      },
      "explanation": "The LOEO fragility is concentrated in the cell whose full-sample MEMP is almost exactly 0.5 (`0.501155`): with the family median sitting on the knife-edge, removing any single event that tips the median across 0.5 flips the sign, so a majority of leave-outs flip while the rest of the surface is leave-out stable."
    },
    "loyo_affected_cells": [
      {
        "cell_key": "FOMC|5d|raw_return",
        "flips": 5,
        "of": 8
      },
      {
        "cell_key": "FOMC|5d|sar",
        "flips": 1,
        "of": 8
      },
      {
        "cell_key": "OPEC|1d|raw_return",
        "flips": 1,
        "of": 8
      },
      {
        "cell_key": "OPEC|1d|spy_relative_ar",
        "flips": 2,
        "of": 8
      },
      {
        "cell_key": "OPEC|5d|sector_relative_ar",
        "flips": 1,
        "of": 8
      }
    ]
  },
  "whole_mission_conclusion": {
    "statement": "Mission I rejects the blanket idea that major event windows are generally more extreme than ordinary periods. Event exceptionalism is family-, horizon-, and metric-specific. FOMC shows the clearest broad pattern at 1d; that coherence weakens by 5d. OPEC is mixed at 1d and 5d and uniformly below ordinary response magnitude at 20d, but with limited cross-horizon consistency.",
    "clarifier": "The word \"rejects\" here refers to the broad descriptive narrative, not a formal hypothesis test. Mission I ran no significance test, computed no p-value, and declared no null rejected. It reports where a frozen descriptive comparison did and did not find event windows to sit away from ordinary-period magnitude."
  },
  "unresolved_or_limits": [
    "There is no anticipation or timing-robustness layer here and no beta-robustness layer; those are later robustness questions, not established here.",
    "The robustness questions enumerated in the non-claims — alternative assets, rolling beta, anticipation / pre-event drift, cross-family collisions — are future work and are deliberately not answered here.",
    "No p-values are computed and no FDR pool is created. Avoiding p-values does not remove multiple-comparison exposure; the only protection claimed here is that all 20 statistics were frozen in i0-v1 before any outcome existed and every one is reported."
  ],
  "non_claims": [
    "causality;",
    "prediction;",
    "tradeability;",
    "alpha;",
    "single-event significance;",
    "permanent asset effects;",
    "cross-family comparability of raw magnitudes;",
    "robustness to alternative primary assets;",
    "robustness to rolling beta;",
    "immunity to anticipation / pre-event drift;",
    "immunity to cross-family event collisions;",
    "mechanism causality."
  ]
};
