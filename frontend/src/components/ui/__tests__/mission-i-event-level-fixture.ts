/**
 * Mission I event-level fixture (the additive `event_level` block of
 * GET /evidence/mission-i, contract mission-i-evidence-v2, published by
 * E1).  A generated capture of the live tracked-publication payload from
 * the backend builder (`routes.mission_i_evidence.
 * build_mission_i_evidence_summary`) - no value below was hand-retyped,
 * and no research value is recomputed here.  All 904 published per-event
 * rows are present, cell-grouped in the frozen 20-cell order with each
 * cell's rows in the publication's ascending anchor-session order.
 * Not a test file - imported by the Mission I fixture and the drilldown
 * suites.
 */
import type { MissionIEventLevel } from "@/lib/api";

/** Fresh deep copy per call so sentinel-mutation tests never leak. */
export function missionIEventLevelFixture(): MissionIEventLevel {
  return structuredClone(MISSION_I_EVENT_LEVEL);
}

const MISSION_I_EVENT_LEVEL: MissionIEventLevel = {
  "source": {
    "artifact": "stats/I2B_MEMP_PRIMARY_COMPARISON.md",
    "sha256": "96845f68746e10c671b1dd0fbbd9633df0a683f7ba945e53bcb253b30d560213",
    "bytes": 101773,
    "row_count": 904
  },
  "method": {
    "percentile_definition": "For each cell the ordinary reference multiset R is the complete set of that cell's reference responses (duplicates kept). An event's magnitude percentile is the mid-rank percentile of its absolute response within the absolute references:",
    "aggregate_definition": "MEMP is the median of those percentiles across the family's events.",
    "signed_definition": "The signed-percentile median applies the identical mid-rank rule to signed values.",
    "ordering_statement": "Never ordered by percentile, response magnitude, or MEMP contribution.",
    "precision_policy": "published percentile strings decode losslessly to the publication's mid-rank grid over the published reference count; each cell median is recomputed exactly on that grid and compared to the published aggregate as an exact decimal string at the published six-decimal precision; no numeric tolerance is applied and an unreconciled cell refuses service",
    "claim_ceiling": "the tracked event-level rows reconcile internally to the published Mission I aggregate record; the original price data and ordinary-period reference distributions are not independently reproduced"
  },
  "total_rows": 904,
  "family_counts": {
    "FOMC": 520,
    "OPEC": 384
  },
  "cells": [
    {
      "cell": 1,
      "cell_key": "FOMC|1d|raw_return",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "raw_return",
      "event_n": 65,
      "published": {
        "memp": "0.674559",
        "signed_percentile_median": "0.339207"
      },
      "recomputed": {
        "memp": "0.674559",
        "signed_percentile_median": "0.339207"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "0.014767",
          "abs_mid_rank_pct": "0.663546",
          "signed_pct": "0.821586"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-0.036312",
          "abs_mid_rank_pct": "0.939978",
          "signed_pct": "0.028634"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "-0.009843",
          "abs_mid_rank_pct": "0.485683",
          "signed_pct": "0.244493"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "-0.004197",
          "abs_mid_rank_pct": "0.230176",
          "signed_pct": "0.374449"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "0.009332",
          "abs_mid_rank_pct": "0.463106",
          "signed_pct": "0.721916"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "-0.008334",
          "abs_mid_rank_pct": "0.424559",
          "signed_pct": "0.272026"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "-0.005558",
          "abs_mid_rank_pct": "0.301762",
          "signed_pct": "0.339207"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.000217",
          "abs_mid_rank_pct": "0.013216",
          "signed_pct": "0.499449"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "-0.011202",
          "abs_mid_rank_pct": "0.544053",
          "signed_pct": "0.216960"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.013939",
          "abs_mid_rank_pct": "0.640419",
          "signed_pct": "0.167401"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "0.012881",
          "abs_mid_rank_pct": "0.606278",
          "signed_pct": "0.790749"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "0.002866",
          "abs_mid_rank_pct": "0.159692",
          "signed_pct": "0.574339"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-0.041712",
          "abs_mid_rank_pct": "0.953194",
          "signed_pct": "0.020374"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.008838",
          "abs_mid_rank_pct": "0.447137",
          "signed_pct": "0.263767"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "-0.015165",
          "abs_mid_rank_pct": "0.674559",
          "signed_pct": "0.154185"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "0.031277",
          "abs_mid_rank_pct": "0.907489",
          "signed_pct": "0.950991"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "0.010046",
          "abs_mid_rank_pct": "0.493392",
          "signed_pct": "0.734581"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "0.017861",
          "abs_mid_rank_pct": "0.743392",
          "signed_pct": "0.866740"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-0.136557",
          "abs_mid_rank_pct": "0.999449",
          "signed_pct": "0.000551"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-0.040272",
          "abs_mid_rank_pct": "0.948238",
          "signed_pct": "0.023678"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.093057",
          "abs_mid_rank_pct": "0.996145",
          "signed_pct": "0.002203"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.017862",
          "abs_mid_rank_pct": "0.743392",
          "signed_pct": "0.123348"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "-0.005513",
          "abs_mid_rank_pct": "0.300110",
          "signed_pct": "0.339207"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "-0.022684",
          "abs_mid_rank_pct": "0.825441",
          "signed_pct": "0.081498"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "-0.004267",
          "abs_mid_rank_pct": "0.235132",
          "signed_pct": "0.371145"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.017903",
          "abs_mid_rank_pct": "0.744493",
          "signed_pct": "0.867291"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "0.005448",
          "abs_mid_rank_pct": "0.297357",
          "signed_pct": "0.638216"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "0.011822",
          "abs_mid_rank_pct": "0.568282",
          "signed_pct": "0.774229"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-0.050310",
          "abs_mid_rank_pct": "0.973018",
          "signed_pct": "0.012665"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "0.006351",
          "abs_mid_rank_pct": "0.341960",
          "signed_pct": "0.656388"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "0.038033",
          "abs_mid_rank_pct": "0.943833",
          "signed_pct": "0.970815"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-0.016129",
          "abs_mid_rank_pct": "0.696035",
          "signed_pct": "0.145925"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "0.001859",
          "abs_mid_rank_pct": "0.096916",
          "signed_pct": "0.538546"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-0.021068",
          "abs_mid_rank_pct": "0.806718",
          "signed_pct": "0.090308"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-0.010849",
          "abs_mid_rank_pct": "0.527533",
          "signed_pct": "0.224119"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "-0.028934",
          "abs_mid_rank_pct": "0.888767",
          "signed_pct": "0.052863"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.035950",
          "abs_mid_rank_pct": "0.938326",
          "signed_pct": "0.029185"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "0.000159",
          "abs_mid_rank_pct": "0.007709",
          "signed_pct": "0.496145"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-0.022811",
          "abs_mid_rank_pct": "0.825441",
          "signed_pct": "0.081498"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "-0.007375",
          "abs_mid_rank_pct": "0.382709",
          "signed_pct": "0.294053"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "-0.018291",
          "abs_mid_rank_pct": "0.752203",
          "signed_pct": "0.118392"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.026667",
          "abs_mid_rank_pct": "0.871145",
          "signed_pct": "0.931167"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-0.027848",
          "abs_mid_rank_pct": "0.881608",
          "signed_pct": "0.055066"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.054507",
          "abs_mid_rank_pct": "0.977423",
          "signed_pct": "0.011013"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "0.019136",
          "abs_mid_rank_pct": "0.773128",
          "signed_pct": "0.881057"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.016987",
          "abs_mid_rank_pct": "0.722467",
          "signed_pct": "0.131608"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "-0.014510",
          "abs_mid_rank_pct": "0.657489",
          "signed_pct": "0.161344"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.056741",
          "abs_mid_rank_pct": "0.979075",
          "signed_pct": "0.988436"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.048305",
          "abs_mid_rank_pct": "0.967511",
          "signed_pct": "0.982379"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-0.031187",
          "abs_mid_rank_pct": "0.907489",
          "signed_pct": "0.043502"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.014748",
          "abs_mid_rank_pct": "0.662996",
          "signed_pct": "0.821035"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.016380",
          "abs_mid_rank_pct": "0.706498",
          "signed_pct": "0.844163"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.015803",
          "abs_mid_rank_pct": "0.690529",
          "signed_pct": "0.146476"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-0.044784",
          "abs_mid_rank_pct": "0.963106",
          "signed_pct": "0.015419"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "0.028292",
          "abs_mid_rank_pct": "0.884912",
          "signed_pct": "0.938326"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.005416",
          "abs_mid_rank_pct": "0.296256",
          "signed_pct": "0.637665"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.008795",
          "abs_mid_rank_pct": "0.446035",
          "signed_pct": "0.263767"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.011162",
          "abs_mid_rank_pct": "0.542952",
          "signed_pct": "0.760463"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "-0.006761",
          "abs_mid_rank_pct": "0.365639",
          "signed_pct": "0.302863"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.024140",
          "abs_mid_rank_pct": "0.841410",
          "signed_pct": "0.913546"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.007606",
          "abs_mid_rank_pct": "0.394824",
          "signed_pct": "0.681718"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.012009",
          "abs_mid_rank_pct": "0.575441",
          "signed_pct": "0.202643"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "0.026687",
          "abs_mid_rank_pct": "0.871145",
          "signed_pct": "0.931167"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.000836",
          "abs_mid_rank_pct": "0.046256",
          "signed_pct": "0.513216"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "0.005220",
          "abs_mid_rank_pct": "0.282489",
          "signed_pct": "0.631608"
        }
      ]
    },
    {
      "cell": 2,
      "cell_key": "FOMC|1d|spy_relative_ar",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "spy_relative_ar",
      "event_n": 65,
      "published": {
        "memp": "0.672357",
        "signed_percentile_median": "0.405286"
      },
      "recomputed": {
        "memp": "0.672357",
        "signed_percentile_median": "0.405286"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "0.015903",
          "abs_mid_rank_pct": "0.791300",
          "signed_pct": "0.902533"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-0.011315",
          "abs_mid_rank_pct": "0.651982",
          "signed_pct": "0.178414"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "-0.007640",
          "abs_mid_rank_pct": "0.487335",
          "signed_pct": "0.258260"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "-0.006714",
          "abs_mid_rank_pct": "0.441630",
          "signed_pct": "0.283590"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "0.003885",
          "abs_mid_rank_pct": "0.269824",
          "signed_pct": "0.638767"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "-0.011128",
          "abs_mid_rank_pct": "0.647026",
          "signed_pct": "0.180617"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "0.004210",
          "abs_mid_rank_pct": "0.292952",
          "signed_pct": "0.651432"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.016495",
          "abs_mid_rank_pct": "0.803965",
          "signed_pct": "0.908040"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "-0.019985",
          "abs_mid_rank_pct": "0.863987",
          "signed_pct": "0.069934"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.025234",
          "abs_mid_rank_pct": "0.912445",
          "signed_pct": "0.042401"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "0.015040",
          "abs_mid_rank_pct": "0.773678",
          "signed_pct": "0.892621"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "-0.006688",
          "abs_mid_rank_pct": "0.440529",
          "signed_pct": "0.284692"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-0.033004",
          "abs_mid_rank_pct": "0.955947",
          "signed_pct": "0.019273"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.008772",
          "abs_mid_rank_pct": "0.545705",
          "signed_pct": "0.231278"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "-0.012502",
          "abs_mid_rank_pct": "0.691630",
          "signed_pct": "0.159141"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "0.022658",
          "abs_mid_rank_pct": "0.890969",
          "signed_pct": "0.946035"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "0.006801",
          "abs_mid_rank_pct": "0.444383",
          "signed_pct": "0.726322"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-0.024172",
          "abs_mid_rank_pct": "0.904185",
          "signed_pct": "0.047907"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-0.027133",
          "abs_mid_rank_pct": "0.928414",
          "signed_pct": "0.032489"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-0.030962",
          "abs_mid_rank_pct": "0.946586",
          "signed_pct": "0.024780"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.035407",
          "abs_mid_rank_pct": "0.968612",
          "signed_pct": "0.013216"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.014294",
          "abs_mid_rank_pct": "0.758260",
          "signed_pct": "0.125000"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "0.003282",
          "abs_mid_rank_pct": "0.235132",
          "signed_pct": "0.627753"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "-0.022456",
          "abs_mid_rank_pct": "0.889317",
          "signed_pct": "0.056167"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "-0.009859",
          "abs_mid_rank_pct": "0.594714",
          "signed_pct": "0.206498"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.009303",
          "abs_mid_rank_pct": "0.575441",
          "signed_pct": "0.790198"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "0.019998",
          "abs_mid_rank_pct": "0.863987",
          "signed_pct": "0.933921"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "0.005449",
          "abs_mid_rank_pct": "0.367291",
          "signed_pct": "0.688877"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-0.049978",
          "abs_mid_rank_pct": "0.986784",
          "signed_pct": "0.004956"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "0.002204",
          "abs_mid_rank_pct": "0.159141",
          "signed_pct": "0.590308"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "0.025883",
          "abs_mid_rank_pct": "0.919053",
          "signed_pct": "0.958150"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-0.020842",
          "abs_mid_rank_pct": "0.875000",
          "signed_pct": "0.062225"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "0.010678",
          "abs_mid_rank_pct": "0.630507",
          "signed_pct": "0.818833"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-0.016130",
          "abs_mid_rank_pct": "0.797357",
          "signed_pct": "0.107930"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-0.023360",
          "abs_mid_rank_pct": "0.895374",
          "signed_pct": "0.052313"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "0.006609",
          "abs_mid_rank_pct": "0.438877",
          "signed_pct": "0.724119"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.002854",
          "abs_mid_rank_pct": "0.210352",
          "signed_pct": "0.405286"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "-0.012383",
          "abs_mid_rank_pct": "0.686674",
          "signed_pct": "0.162996"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-0.014411",
          "abs_mid_rank_pct": "0.761564",
          "signed_pct": "0.123348"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "0.002922",
          "abs_mid_rank_pct": "0.212555",
          "signed_pct": "0.616189"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "0.006171",
          "abs_mid_rank_pct": "0.413546",
          "signed_pct": "0.710352"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.012110",
          "abs_mid_rank_pct": "0.677863",
          "signed_pct": "0.846366"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-0.030552",
          "abs_mid_rank_pct": "0.944934",
          "signed_pct": "0.025330"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.047424",
          "abs_mid_rank_pct": "0.985132",
          "signed_pct": "0.006057"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "0.006739",
          "abs_mid_rank_pct": "0.441630",
          "signed_pct": "0.725220"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.010357",
          "abs_mid_rank_pct": "0.614537",
          "signed_pct": "0.197687"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "0.002018",
          "abs_mid_rank_pct": "0.145925",
          "signed_pct": "0.583150"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.037577",
          "abs_mid_rank_pct": "0.971366",
          "signed_pct": "0.982379"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.045096",
          "abs_mid_rank_pct": "0.982379",
          "signed_pct": "0.990088"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-0.044275",
          "abs_mid_rank_pct": "0.981278",
          "signed_pct": "0.007709"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.011444",
          "abs_mid_rank_pct": "0.656938",
          "signed_pct": "0.834251"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.007026",
          "abs_mid_rank_pct": "0.457599",
          "signed_pct": "0.732379"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.017816",
          "abs_mid_rank_pct": "0.833700",
          "signed_pct": "0.087004"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-0.030623",
          "abs_mid_rank_pct": "0.944934",
          "signed_pct": "0.025330"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "0.011228",
          "abs_mid_rank_pct": "0.648678",
          "signed_pct": "0.828194"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.001084",
          "abs_mid_rank_pct": "0.084251",
          "signed_pct": "0.558370"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.008488",
          "abs_mid_rank_pct": "0.531388",
          "signed_pct": "0.237885"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.005795",
          "abs_mid_rank_pct": "0.389868",
          "signed_pct": "0.700991"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "-0.003870",
          "abs_mid_rank_pct": "0.269273",
          "signed_pct": "0.369493"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.017172",
          "abs_mid_rank_pct": "0.822137",
          "signed_pct": "0.915749"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.009955",
          "abs_mid_rank_pct": "0.598018",
          "signed_pct": "0.802313"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.008257",
          "abs_mid_rank_pct": "0.518172",
          "signed_pct": "0.245044"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "0.022015",
          "abs_mid_rank_pct": "0.886564",
          "signed_pct": "0.943833"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.011834",
          "abs_mid_rank_pct": "0.672357",
          "signed_pct": "0.844163"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "0.002893",
          "abs_mid_rank_pct": "0.210903",
          "signed_pct": "0.615639"
        }
      ]
    },
    {
      "cell": 3,
      "cell_key": "FOMC|1d|sector_relative_ar",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "sector_relative_ar",
      "event_n": 65,
      "published": {
        "memp": "0.662996",
        "signed_percentile_median": "0.386013"
      },
      "recomputed": {
        "memp": "0.662996",
        "signed_percentile_median": "0.386013"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "0.005353",
          "abs_mid_rank_pct": "0.486784",
          "signed_pct": "0.753304"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "0.000596",
          "abs_mid_rank_pct": "0.071035",
          "signed_pct": "0.546806"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "-0.001372",
          "abs_mid_rank_pct": "0.154185",
          "signed_pct": "0.435022"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "0.005139",
          "abs_mid_rank_pct": "0.469163",
          "signed_pct": "0.748348"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "0.008975",
          "abs_mid_rank_pct": "0.693282",
          "signed_pct": "0.855727"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "-0.004758",
          "abs_mid_rank_pct": "0.440529",
          "signed_pct": "0.296256"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "0.003576",
          "abs_mid_rank_pct": "0.346916",
          "signed_pct": "0.691630"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.009112",
          "abs_mid_rank_pct": "0.702643",
          "signed_pct": "0.860132"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "-0.009663",
          "abs_mid_rank_pct": "0.726322",
          "signed_pct": "0.142621"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.010879",
          "abs_mid_rank_pct": "0.765969",
          "signed_pct": "0.126101"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "0.011801",
          "abs_mid_rank_pct": "0.797357",
          "signed_pct": "0.902533"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "-0.001530",
          "abs_mid_rank_pct": "0.163546",
          "signed_pct": "0.430066"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-0.019057",
          "abs_mid_rank_pct": "0.925110",
          "signed_pct": "0.035793"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.004279",
          "abs_mid_rank_pct": "0.402533",
          "signed_pct": "0.317181"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "-0.010311",
          "abs_mid_rank_pct": "0.748899",
          "signed_pct": "0.131608"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "0.011761",
          "abs_mid_rank_pct": "0.795705",
          "signed_pct": "0.901432"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "-0.002529",
          "abs_mid_rank_pct": "0.257159",
          "signed_pct": "0.386013"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-0.015224",
          "abs_mid_rank_pct": "0.877203",
          "signed_pct": "0.063326"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "0.000536",
          "abs_mid_rank_pct": "0.061123",
          "signed_pct": "0.542401"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-0.015037",
          "abs_mid_rank_pct": "0.873348",
          "signed_pct": "0.064427"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.011278",
          "abs_mid_rank_pct": "0.780837",
          "signed_pct": "0.115639"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "0.000126",
          "abs_mid_rank_pct": "0.013216",
          "signed_pct": "0.520374"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "0.004891",
          "abs_mid_rank_pct": "0.449339",
          "signed_pct": "0.740088"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "-0.014735",
          "abs_mid_rank_pct": "0.866189",
          "signed_pct": "0.067731"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "-0.007058",
          "abs_mid_rank_pct": "0.602423",
          "signed_pct": "0.206498"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "-0.000718",
          "abs_mid_rank_pct": "0.083150",
          "signed_pct": "0.469714"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "0.000222",
          "abs_mid_rank_pct": "0.026432",
          "signed_pct": "0.526432"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "-0.005986",
          "abs_mid_rank_pct": "0.535242",
          "signed_pct": "0.241189"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-0.020740",
          "abs_mid_rank_pct": "0.942181",
          "signed_pct": "0.024780"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "-0.004635",
          "abs_mid_rank_pct": "0.432269",
          "signed_pct": "0.301211"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "0.013512",
          "abs_mid_rank_pct": "0.837004",
          "signed_pct": "0.919604"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-0.003052",
          "abs_mid_rank_pct": "0.307269",
          "signed_pct": "0.362335"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "-0.010714",
          "abs_mid_rank_pct": "0.762115",
          "signed_pct": "0.126101"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-0.011993",
          "abs_mid_rank_pct": "0.803965",
          "signed_pct": "0.101322"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-0.023339",
          "abs_mid_rank_pct": "0.956498",
          "signed_pct": "0.018172"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "0.000200",
          "abs_mid_rank_pct": "0.022577",
          "signed_pct": "0.524229"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.010666",
          "abs_mid_rank_pct": "0.761564",
          "signed_pct": "0.126652"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "-0.007113",
          "abs_mid_rank_pct": "0.608480",
          "signed_pct": "0.203744"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-0.005983",
          "abs_mid_rank_pct": "0.535242",
          "signed_pct": "0.241189"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "0.002732",
          "abs_mid_rank_pct": "0.274229",
          "signed_pct": "0.650881"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "0.001340",
          "abs_mid_rank_pct": "0.151982",
          "signed_pct": "0.588106"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.023931",
          "abs_mid_rank_pct": "0.961454",
          "signed_pct": "0.976872"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-0.021122",
          "abs_mid_rank_pct": "0.943833",
          "signed_pct": "0.024780"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.041679",
          "abs_mid_rank_pct": "0.994493",
          "signed_pct": "0.002203"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "0.005888",
          "abs_mid_rank_pct": "0.527533",
          "signed_pct": "0.772577"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.004340",
          "abs_mid_rank_pct": "0.406938",
          "signed_pct": "0.313326"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "0.002017",
          "abs_mid_rank_pct": "0.213106",
          "signed_pct": "0.620044"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.033100",
          "abs_mid_rank_pct": "0.985683",
          "signed_pct": "0.990639"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.038359",
          "abs_mid_rank_pct": "0.991740",
          "signed_pct": "0.995044"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-0.032735",
          "abs_mid_rank_pct": "0.984581",
          "signed_pct": "0.005507"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.006567",
          "abs_mid_rank_pct": "0.572687",
          "signed_pct": "0.795154"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.013902",
          "abs_mid_rank_pct": "0.846916",
          "signed_pct": "0.924559"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.015068",
          "abs_mid_rank_pct": "0.875000",
          "signed_pct": "0.063877"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-0.030609",
          "abs_mid_rank_pct": "0.980176",
          "signed_pct": "0.005507"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "0.017228",
          "abs_mid_rank_pct": "0.905286",
          "signed_pct": "0.952093"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "-0.003610",
          "abs_mid_rank_pct": "0.347467",
          "signed_pct": "0.344163"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.012364",
          "abs_mid_rank_pct": "0.812225",
          "signed_pct": "0.098568"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.001606",
          "abs_mid_rank_pct": "0.173458",
          "signed_pct": "0.598018"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "-0.008173",
          "abs_mid_rank_pct": "0.662996",
          "signed_pct": "0.175661"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.015849",
          "abs_mid_rank_pct": "0.882709",
          "signed_pct": "0.943282"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.004819",
          "abs_mid_rank_pct": "0.446035",
          "signed_pct": "0.738436"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.005747",
          "abs_mid_rank_pct": "0.518172",
          "signed_pct": "0.250000"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "0.025763",
          "abs_mid_rank_pct": "0.970815",
          "signed_pct": "0.980727"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "-0.001852",
          "abs_mid_rank_pct": "0.201542",
          "signed_pct": "0.412445"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "-0.012965",
          "abs_mid_rank_pct": "0.825441",
          "signed_pct": "0.089758"
        }
      ]
    },
    {
      "cell": 4,
      "cell_key": "FOMC|1d|sar",
      "family": "FOMC",
      "horizon": "1d",
      "metric": "sar",
      "event_n": 65,
      "published": {
        "memp": "0.725771",
        "signed_percentile_median": "0.377753"
      },
      "recomputed": {
        "memp": "0.725771",
        "signed_percentile_median": "0.377753"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "1.584840",
          "abs_mid_rank_pct": "0.904185",
          "signed_pct": "0.953744"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-1.467662",
          "abs_mid_rank_pct": "0.887665",
          "signed_pct": "0.060022"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "-0.814767",
          "abs_mid_rank_pct": "0.645925",
          "signed_pct": "0.172907"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "-0.789417",
          "abs_mid_rank_pct": "0.632159",
          "signed_pct": "0.180066"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "0.469262",
          "abs_mid_rank_pct": "0.414097",
          "signed_pct": "0.708150"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "-1.250800",
          "abs_mid_rank_pct": "0.826542",
          "signed_pct": "0.088656"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "0.374938",
          "abs_mid_rank_pct": "0.336454",
          "signed_pct": "0.671806"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "1.311063",
          "abs_mid_rank_pct": "0.846366",
          "signed_pct": "0.925110"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "-1.820884",
          "abs_mid_rank_pct": "0.940529",
          "signed_pct": "0.032489"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-2.339805",
          "abs_mid_rank_pct": "0.968062",
          "signed_pct": "0.017070"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "1.325657",
          "abs_mid_rank_pct": "0.851872",
          "signed_pct": "0.928414"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "-0.663422",
          "abs_mid_rank_pct": "0.559471",
          "signed_pct": "0.225771"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-3.292904",
          "abs_mid_rank_pct": "0.991189",
          "signed_pct": "0.006057"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.778406",
          "abs_mid_rank_pct": "0.625551",
          "signed_pct": "0.184471"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "-1.295299",
          "abs_mid_rank_pct": "0.842511",
          "signed_pct": "0.079295"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "3.110503",
          "abs_mid_rank_pct": "0.989537",
          "signed_pct": "0.996696"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "0.978154",
          "abs_mid_rank_pct": "0.724670",
          "signed_pct": "0.861233"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-3.078020",
          "abs_mid_rank_pct": "0.987885",
          "signed_pct": "0.007159"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-1.956019",
          "abs_mid_rank_pct": "0.948789",
          "signed_pct": "0.028084"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-1.080055",
          "abs_mid_rank_pct": "0.765969",
          "signed_pct": "0.118392"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-1.010099",
          "abs_mid_rank_pct": "0.738436",
          "signed_pct": "0.128855"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.453965",
          "abs_mid_rank_pct": "0.402533",
          "signed_pct": "0.299559"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "0.133647",
          "abs_mid_rank_pct": "0.131057",
          "signed_pct": "0.578744"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "-0.980245",
          "abs_mid_rank_pct": "0.725771",
          "signed_pct": "0.136013"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "-0.358770",
          "abs_mid_rank_pct": "0.318833",
          "signed_pct": "0.345264"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.326417",
          "abs_mid_rank_pct": "0.292952",
          "signed_pct": "0.653084"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "1.138760",
          "abs_mid_rank_pct": "0.790198",
          "signed_pct": "0.896476"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "0.319176",
          "abs_mid_rank_pct": "0.285242",
          "signed_pct": "0.649780"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-3.520424",
          "abs_mid_rank_pct": "0.992841",
          "signed_pct": "0.005507"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "0.140728",
          "abs_mid_rank_pct": "0.133260",
          "signed_pct": "0.579295"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "1.991506",
          "abs_mid_rank_pct": "0.950441",
          "signed_pct": "0.978524"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-1.595470",
          "abs_mid_rank_pct": "0.907489",
          "signed_pct": "0.047357"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "0.790296",
          "abs_mid_rank_pct": "0.633260",
          "signed_pct": "0.813326"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-1.236233",
          "abs_mid_rank_pct": "0.822687",
          "signed_pct": "0.090859"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-1.554109",
          "abs_mid_rank_pct": "0.900330",
          "signed_pct": "0.051211"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "0.460885",
          "abs_mid_rank_pct": "0.405286",
          "signed_pct": "0.704295"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.289216",
          "abs_mid_rank_pct": "0.258260",
          "signed_pct": "0.377753"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "-1.390754",
          "abs_mid_rank_pct": "0.867841",
          "signed_pct": "0.067731"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-1.749477",
          "abs_mid_rank_pct": "0.930066",
          "signed_pct": "0.036894"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "0.342204",
          "abs_mid_rank_pct": "0.309471",
          "signed_pct": "0.659141"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "0.645453",
          "abs_mid_rank_pct": "0.547907",
          "signed_pct": "0.778084"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "1.342040",
          "abs_mid_rank_pct": "0.856828",
          "signed_pct": "0.930066"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-1.399556",
          "abs_mid_rank_pct": "0.868392",
          "signed_pct": "0.067731"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-1.954516",
          "abs_mid_rank_pct": "0.948238",
          "signed_pct": "0.028634"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "0.274449",
          "abs_mid_rank_pct": "0.249449",
          "signed_pct": "0.631608"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.425795",
          "abs_mid_rank_pct": "0.378304",
          "signed_pct": "0.313877"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "0.131502",
          "abs_mid_rank_pct": "0.129956",
          "signed_pct": "0.578194"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "2.789310",
          "abs_mid_rank_pct": "0.982930",
          "signed_pct": "0.992291"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "2.579839",
          "abs_mid_rank_pct": "0.977974",
          "signed_pct": "0.988987"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-2.506870",
          "abs_mid_rank_pct": "0.976872",
          "signed_pct": "0.011564"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.721286",
          "abs_mid_rank_pct": "0.594163",
          "signed_pct": "0.803414"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.436397",
          "abs_mid_rank_pct": "0.386564",
          "signed_pct": "0.696035"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-1.321682",
          "abs_mid_rank_pct": "0.850220",
          "signed_pct": "0.078194"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-1.890993",
          "abs_mid_rank_pct": "0.942731",
          "signed_pct": "0.031388"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "0.671297",
          "abs_mid_rank_pct": "0.564427",
          "signed_pct": "0.787996"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.053742",
          "abs_mid_rank_pct": "0.050661",
          "signed_pct": "0.543502"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.432189",
          "abs_mid_rank_pct": "0.381608",
          "signed_pct": "0.312775"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.307902",
          "abs_mid_rank_pct": "0.277533",
          "signed_pct": "0.646476"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "-0.362372",
          "abs_mid_rank_pct": "0.321586",
          "signed_pct": "0.344163"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "1.347577",
          "abs_mid_rank_pct": "0.857379",
          "signed_pct": "0.930617"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.791801",
          "abs_mid_rank_pct": "0.633260",
          "signed_pct": "0.813326"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.777611",
          "abs_mid_rank_pct": "0.625000",
          "signed_pct": "0.185022"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "1.941022",
          "abs_mid_rank_pct": "0.946035",
          "signed_pct": "0.976322"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.852380",
          "abs_mid_rank_pct": "0.664648",
          "signed_pct": "0.830396"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "0.197043",
          "abs_mid_rank_pct": "0.189978",
          "signed_pct": "0.601872"
        }
      ]
    },
    {
      "cell": 5,
      "cell_key": "FOMC|5d|raw_return",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "raw_return",
      "event_n": 65,
      "published": {
        "memp": "0.501155",
        "signed_percentile_median": "0.447267"
      },
      "recomputed": {
        "memp": "0.501155",
        "signed_percentile_median": "0.447267"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "-0.019101",
          "abs_mid_rank_pct": "0.420323",
          "signed_pct": "0.263279"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-0.054626",
          "abs_mid_rank_pct": "0.849115",
          "signed_pct": "0.059276"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "0.026142",
          "abs_mid_rank_pct": "0.535027",
          "signed_pct": "0.742109"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "0.002076",
          "abs_mid_rank_pct": "0.060816",
          "signed_pct": "0.505774"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "0.012068",
          "abs_mid_rank_pct": "0.284834",
          "signed_pct": "0.612009"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "0.000500",
          "abs_mid_rank_pct": "0.017706",
          "signed_pct": "0.483449"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "-0.012910",
          "abs_mid_rank_pct": "0.304080",
          "signed_pct": "0.319477"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.008503",
          "abs_mid_rank_pct": "0.210162",
          "signed_pct": "0.575828"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "0.005975",
          "abs_mid_rank_pct": "0.149346",
          "signed_pct": "0.548884"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.030170",
          "abs_mid_rank_pct": "0.598152",
          "signed_pct": "0.175520"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "-0.002903",
          "abs_mid_rank_pct": "0.076212",
          "signed_pct": "0.434180"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "-0.003056",
          "abs_mid_rank_pct": "0.083911",
          "signed_pct": "0.431871"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-0.085600",
          "abs_mid_rank_pct": "0.947652",
          "signed_pct": "0.021555"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.009023",
          "abs_mid_rank_pct": "0.220939",
          "signed_pct": "0.357968"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "0.029965",
          "abs_mid_rank_pct": "0.596613",
          "signed_pct": "0.772902"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "0.036197",
          "abs_mid_rank_pct": "0.678984",
          "signed_pct": "0.816012"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "0.039818",
          "abs_mid_rank_pct": "0.716705",
          "signed_pct": "0.834488"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-0.165581",
          "abs_mid_rank_pct": "0.992302",
          "signed_pct": "0.002309"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-0.181190",
          "abs_mid_rank_pct": "0.993841",
          "signed_pct": "0.002309"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-0.135414",
          "abs_mid_rank_pct": "0.986143",
          "signed_pct": "0.004619"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.042472",
          "abs_mid_rank_pct": "0.744419",
          "signed_pct": "0.107005"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.011132",
          "abs_mid_rank_pct": "0.267898",
          "signed_pct": "0.334103"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "-0.101471",
          "abs_mid_rank_pct": "0.967667",
          "signed_pct": "0.012317"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "0.082467",
          "abs_mid_rank_pct": "0.943033",
          "signed_pct": "0.966128"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "0.010803",
          "abs_mid_rank_pct": "0.260970",
          "signed_pct": "0.600462"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.045488",
          "abs_mid_rank_pct": "0.782140",
          "signed_pct": "0.874519"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "-0.072468",
          "abs_mid_rank_pct": "0.919938",
          "signed_pct": "0.028483"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "0.024081",
          "abs_mid_rank_pct": "0.501155",
          "signed_pct": "0.728253"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-0.045886",
          "abs_mid_rank_pct": "0.786759",
          "signed_pct": "0.090069"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "-0.007939",
          "abs_mid_rank_pct": "0.193995",
          "signed_pct": "0.373364"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "0.091821",
          "abs_mid_rank_pct": "0.959199",
          "signed_pct": "0.976905"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-0.010664",
          "abs_mid_rank_pct": "0.260200",
          "signed_pct": "0.339492"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "-0.001811",
          "abs_mid_rank_pct": "0.053118",
          "signed_pct": "0.447267"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "0.004712",
          "abs_mid_rank_pct": "0.126251",
          "signed_pct": "0.538876"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-0.037139",
          "abs_mid_rank_pct": "0.688992",
          "signed_pct": "0.132410"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "-0.081139",
          "abs_mid_rank_pct": "0.939954",
          "signed_pct": "0.023095"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.018211",
          "abs_mid_rank_pct": "0.403387",
          "signed_pct": "0.272517"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "0.014152",
          "abs_mid_rank_pct": "0.324865",
          "signed_pct": "0.635874"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-0.041474",
          "abs_mid_rank_pct": "0.735951",
          "signed_pct": "0.108545"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "0.003207",
          "abs_mid_rank_pct": "0.086220",
          "signed_pct": "0.518091"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "-0.000394",
          "abs_mid_rank_pct": "0.014627",
          "signed_pct": "0.466513"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.016825",
          "abs_mid_rank_pct": "0.374904",
          "signed_pct": "0.659738"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "0.020253",
          "abs_mid_rank_pct": "0.443418",
          "signed_pct": "0.695920"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.028826",
          "abs_mid_rank_pct": "0.581986",
          "signed_pct": "0.181678"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "-0.054014",
          "abs_mid_rank_pct": "0.846805",
          "signed_pct": "0.060816"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.018625",
          "abs_mid_rank_pct": "0.410316",
          "signed_pct": "0.268668"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "-0.027593",
          "abs_mid_rank_pct": "0.558891",
          "signed_pct": "0.196305"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.054984",
          "abs_mid_rank_pct": "0.849885",
          "signed_pct": "0.908391"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.011740",
          "abs_mid_rank_pct": "0.280216",
          "signed_pct": "0.610470"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-0.057344",
          "abs_mid_rank_pct": "0.861432",
          "signed_pct": "0.054657"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.024580",
          "abs_mid_rank_pct": "0.510393",
          "signed_pct": "0.731332"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.040224",
          "abs_mid_rank_pct": "0.722094",
          "signed_pct": "0.837567"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.007585",
          "abs_mid_rank_pct": "0.187837",
          "signed_pct": "0.377213"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-0.105353",
          "abs_mid_rank_pct": "0.970747",
          "signed_pct": "0.011547"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "-0.028847",
          "abs_mid_rank_pct": "0.581986",
          "signed_pct": "0.181678"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.018567",
          "abs_mid_rank_pct": "0.409546",
          "signed_pct": "0.678984"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "0.024699",
          "abs_mid_rank_pct": "0.511162",
          "signed_pct": "0.731332"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.017922",
          "abs_mid_rank_pct": "0.400308",
          "signed_pct": "0.672825"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "0.012405",
          "abs_mid_rank_pct": "0.291763",
          "signed_pct": "0.614319"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.066294",
          "abs_mid_rank_pct": "0.898383",
          "signed_pct": "0.934565"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.059457",
          "abs_mid_rank_pct": "0.869130",
          "signed_pct": "0.919938"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.023359",
          "abs_mid_rank_pct": "0.490377",
          "signed_pct": "0.230947"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "-0.001958",
          "abs_mid_rank_pct": "0.056197",
          "signed_pct": "0.447267"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.012540",
          "abs_mid_rank_pct": "0.293303",
          "signed_pct": "0.615858"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "0.003579",
          "abs_mid_rank_pct": "0.095458",
          "signed_pct": "0.521940"
        }
      ]
    },
    {
      "cell": 6,
      "cell_key": "FOMC|5d|spy_relative_ar",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "spy_relative_ar",
      "event_n": 65,
      "published": {
        "memp": "0.527329",
        "signed_percentile_median": "0.504234"
      },
      "recomputed": {
        "memp": "0.527329",
        "signed_percentile_median": "0.504234"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "0.031378",
          "abs_mid_rank_pct": "0.725943",
          "signed_pct": "0.866821"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-0.015429",
          "abs_mid_rank_pct": "0.435720",
          "signed_pct": "0.303310"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "0.002206",
          "abs_mid_rank_pct": "0.066205",
          "signed_pct": "0.568899"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "0.005028",
          "abs_mid_rank_pct": "0.142417",
          "signed_pct": "0.608930"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "-0.004310",
          "abs_mid_rank_pct": "0.122402",
          "signed_pct": "0.476520"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "-0.005847",
          "abs_mid_rank_pct": "0.162433",
          "signed_pct": "0.456505"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "0.013757",
          "abs_mid_rank_pct": "0.393380",
          "signed_pct": "0.721324"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.015434",
          "abs_mid_rank_pct": "0.435720",
          "signed_pct": "0.739030"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "-0.013309",
          "abs_mid_rank_pct": "0.380293",
          "signed_pct": "0.335643"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.023421",
          "abs_mid_rank_pct": "0.610470",
          "signed_pct": "0.209392"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "0.011764",
          "abs_mid_rank_pct": "0.339492",
          "signed_pct": "0.697460"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "0.000961",
          "abs_mid_rank_pct": "0.026174",
          "signed_pct": "0.545804"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-0.053795",
          "abs_mid_rank_pct": "0.903772",
          "signed_pct": "0.030023"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.002030",
          "abs_mid_rank_pct": "0.062356",
          "signed_pct": "0.504234"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "0.020233",
          "abs_mid_rank_pct": "0.541186",
          "signed_pct": "0.784450"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "0.019754",
          "abs_mid_rank_pct": "0.532717",
          "signed_pct": "0.779831"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "0.020713",
          "abs_mid_rank_pct": "0.549654",
          "signed_pct": "0.786759"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-0.126213",
          "abs_mid_rank_pct": "0.992302",
          "signed_pct": "0.003849"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-0.035733",
          "abs_mid_rank_pct": "0.782910",
          "signed_pct": "0.105466"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-0.104856",
          "abs_mid_rank_pct": "0.986913",
          "signed_pct": "0.006159"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.019462",
          "abs_mid_rank_pct": "0.525789",
          "signed_pct": "0.251732"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.032631",
          "abs_mid_rank_pct": "0.747498",
          "signed_pct": "0.127021"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "-0.057529",
          "abs_mid_rank_pct": "0.916859",
          "signed_pct": "0.023865"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "0.073987",
          "abs_mid_rank_pct": "0.956890",
          "signed_pct": "0.969207"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "0.013594",
          "abs_mid_rank_pct": "0.387991",
          "signed_pct": "0.719784"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.025617",
          "abs_mid_rank_pct": "0.649731",
          "signed_pct": "0.833718"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "-0.051145",
          "abs_mid_rank_pct": "0.894534",
          "signed_pct": "0.035412"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "0.028034",
          "abs_mid_rank_pct": "0.682833",
          "signed_pct": "0.844496"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-0.050323",
          "abs_mid_rank_pct": "0.890685",
          "signed_pct": "0.037721"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "-0.008281",
          "abs_mid_rank_pct": "0.230177",
          "signed_pct": "0.418014"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "0.099608",
          "abs_mid_rank_pct": "0.983064",
          "signed_pct": "0.989992"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-0.008297",
          "abs_mid_rank_pct": "0.230947",
          "signed_pct": "0.418014"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "0.000881",
          "abs_mid_rank_pct": "0.024634",
          "signed_pct": "0.545035"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-0.050597",
          "abs_mid_rank_pct": "0.891455",
          "signed_pct": "0.036952"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-0.059082",
          "abs_mid_rank_pct": "0.923018",
          "signed_pct": "0.020785"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "0.003488",
          "abs_mid_rank_pct": "0.095458",
          "signed_pct": "0.581986"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.019511",
          "abs_mid_rank_pct": "0.527329",
          "signed_pct": "0.250962"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "-0.019286",
          "abs_mid_rank_pct": "0.521940",
          "signed_pct": "0.254042"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-0.023296",
          "abs_mid_rank_pct": "0.609700",
          "signed_pct": "0.209392"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "0.005181",
          "abs_mid_rank_pct": "0.147036",
          "signed_pct": "0.609700"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "0.028140",
          "abs_mid_rank_pct": "0.682833",
          "signed_pct": "0.844496"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.017190",
          "abs_mid_rank_pct": "0.478060",
          "signed_pct": "0.755196"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-0.003312",
          "abs_mid_rank_pct": "0.091609",
          "signed_pct": "0.488068"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.040664",
          "abs_mid_rank_pct": "0.832948",
          "signed_pct": "0.072363"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "-0.056190",
          "abs_mid_rank_pct": "0.911470",
          "signed_pct": "0.026944"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.006813",
          "abs_mid_rank_pct": "0.187067",
          "signed_pct": "0.444188"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "0.001110",
          "abs_mid_rank_pct": "0.034642",
          "signed_pct": "0.548884"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.020464",
          "abs_mid_rank_pct": "0.546574",
          "signed_pct": "0.785989"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.012466",
          "abs_mid_rank_pct": "0.357198",
          "signed_pct": "0.702079"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-0.088863",
          "abs_mid_rank_pct": "0.973056",
          "signed_pct": "0.009238"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.019412",
          "abs_mid_rank_pct": "0.523480",
          "signed_pct": "0.777521"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.006568",
          "abs_mid_rank_pct": "0.180908",
          "signed_pct": "0.628176"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.018004",
          "abs_mid_rank_pct": "0.495766",
          "signed_pct": "0.270208"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-0.046985",
          "abs_mid_rank_pct": "0.867590",
          "signed_pct": "0.050038"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "-0.047351",
          "abs_mid_rank_pct": "0.870670",
          "signed_pct": "0.049269"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.022362",
          "abs_mid_rank_pct": "0.585835",
          "signed_pct": "0.806774"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.004440",
          "abs_mid_rank_pct": "0.129330",
          "signed_pct": "0.472671"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.013917",
          "abs_mid_rank_pct": "0.398768",
          "signed_pct": "0.724403"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "0.006814",
          "abs_mid_rank_pct": "0.187067",
          "signed_pct": "0.631255"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.019177",
          "abs_mid_rank_pct": "0.518861",
          "signed_pct": "0.774442"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.032276",
          "abs_mid_rank_pct": "0.742109",
          "signed_pct": "0.872209"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.020711",
          "abs_mid_rank_pct": "0.549654",
          "signed_pct": "0.237105"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "-0.007651",
          "abs_mid_rank_pct": "0.214011",
          "signed_pct": "0.426482"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.026811",
          "abs_mid_rank_pct": "0.666667",
          "signed_pct": "0.839107"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "0.027097",
          "abs_mid_rank_pct": "0.669746",
          "signed_pct": "0.839877"
        }
      ]
    },
    {
      "cell": 7,
      "cell_key": "FOMC|5d|sector_relative_ar",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "sector_relative_ar",
      "event_n": 65,
      "published": {
        "memp": "0.408006",
        "signed_percentile_median": "0.501925"
      },
      "recomputed": {
        "memp": "0.408006",
        "signed_percentile_median": "0.501925"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "0.025620",
          "abs_mid_rank_pct": "0.787529",
          "signed_pct": "0.883757"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-0.001701",
          "abs_mid_rank_pct": "0.073903",
          "signed_pct": "0.501925"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "-0.007007",
          "abs_mid_rank_pct": "0.294072",
          "signed_pct": "0.381832"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "0.018299",
          "abs_mid_rank_pct": "0.648961",
          "signed_pct": "0.833718"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "-0.006537",
          "abs_mid_rank_pct": "0.277136",
          "signed_pct": "0.390300"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "0.001215",
          "abs_mid_rank_pct": "0.054657",
          "signed_pct": "0.563510"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "0.009377",
          "abs_mid_rank_pct": "0.384142",
          "signed_pct": "0.715935"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.002694",
          "abs_mid_rank_pct": "0.124711",
          "signed_pct": "0.597383"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "0.002896",
          "abs_mid_rank_pct": "0.131640",
          "signed_pct": "0.599692"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.002626",
          "abs_mid_rank_pct": "0.120092",
          "signed_pct": "0.476520"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "0.012570",
          "abs_mid_rank_pct": "0.491917",
          "signed_pct": "0.770593"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "0.003998",
          "abs_mid_rank_pct": "0.173210",
          "signed_pct": "0.620477"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-0.032503",
          "abs_mid_rank_pct": "0.867590",
          "signed_pct": "0.050038"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "0.001033",
          "abs_mid_rank_pct": "0.039261",
          "signed_pct": "0.557352"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "0.002573",
          "abs_mid_rank_pct": "0.119323",
          "signed_pct": "0.595843"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "0.017011",
          "abs_mid_rank_pct": "0.617398",
          "signed_pct": "0.826020"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "0.011690",
          "abs_mid_rank_pct": "0.458045",
          "signed_pct": "0.749808"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-0.063350",
          "abs_mid_rank_pct": "0.976905",
          "signed_pct": "0.006159"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-0.001580",
          "abs_mid_rank_pct": "0.070054",
          "signed_pct": "0.504234"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-0.047305",
          "abs_mid_rank_pct": "0.943803",
          "signed_pct": "0.015396"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.001980",
          "abs_mid_rank_pct": "0.090839",
          "signed_pct": "0.492687"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.005817",
          "abs_mid_rank_pct": "0.242494",
          "signed_pct": "0.409546"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "-0.034949",
          "abs_mid_rank_pct": "0.889915",
          "signed_pct": "0.038491"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "0.025630",
          "abs_mid_rank_pct": "0.787529",
          "signed_pct": "0.883757"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "-0.003331",
          "abs_mid_rank_pct": "0.148576",
          "signed_pct": "0.458814"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.003764",
          "abs_mid_rank_pct": "0.162433",
          "signed_pct": "0.613549"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "-0.043069",
          "abs_mid_rank_pct": "0.930716",
          "signed_pct": "0.018476"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "-0.006248",
          "abs_mid_rank_pct": "0.264049",
          "signed_pct": "0.396459"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-0.018541",
          "abs_mid_rank_pct": "0.651270",
          "signed_pct": "0.183218"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "-0.013981",
          "abs_mid_rank_pct": "0.531948",
          "signed_pct": "0.257121"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "0.064335",
          "abs_mid_rank_pct": "0.977675",
          "signed_pct": "0.983834"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "0.003647",
          "abs_mid_rank_pct": "0.159353",
          "signed_pct": "0.612779"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "0.002422",
          "abs_mid_rank_pct": "0.110855",
          "signed_pct": "0.592764"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-0.028993",
          "abs_mid_rank_pct": "0.824480",
          "signed_pct": "0.075443"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-0.048367",
          "abs_mid_rank_pct": "0.946112",
          "signed_pct": "0.014627"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "-0.005112",
          "abs_mid_rank_pct": "0.215550",
          "signed_pct": "0.423403"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.009244",
          "abs_mid_rank_pct": "0.380293",
          "signed_pct": "0.334103"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "-0.002818",
          "abs_mid_rank_pct": "0.128560",
          "signed_pct": "0.470362"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-0.008442",
          "abs_mid_rank_pct": "0.350269",
          "signed_pct": "0.351039"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "-0.003630",
          "abs_mid_rank_pct": "0.158584",
          "signed_pct": "0.454196"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "0.010184",
          "abs_mid_rank_pct": "0.411085",
          "signed_pct": "0.730562"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.010808",
          "abs_mid_rank_pct": "0.430331",
          "signed_pct": "0.738260"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-0.000567",
          "abs_mid_rank_pct": "0.023095",
          "signed_pct": "0.528099"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.032581",
          "abs_mid_rank_pct": "0.867590",
          "signed_pct": "0.050038"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "-0.048519",
          "abs_mid_rank_pct": "0.946882",
          "signed_pct": "0.014627"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.003167",
          "abs_mid_rank_pct": "0.143187",
          "signed_pct": "0.461124"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "0.008650",
          "abs_mid_rank_pct": "0.357198",
          "signed_pct": "0.703618"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.021210",
          "abs_mid_rank_pct": "0.709777",
          "signed_pct": "0.859122"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.014893",
          "abs_mid_rank_pct": "0.557352",
          "signed_pct": "0.802156"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-0.066632",
          "abs_mid_rank_pct": "0.981524",
          "signed_pct": "0.006159"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.016640",
          "abs_mid_rank_pct": "0.607390",
          "signed_pct": "0.822171"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.015447",
          "abs_mid_rank_pct": "0.576597",
          "signed_pct": "0.809084"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.024248",
          "abs_mid_rank_pct": "0.764434",
          "signed_pct": "0.110085"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-0.055285",
          "abs_mid_rank_pct": "0.962279",
          "signed_pct": "0.010778"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "-0.023590",
          "abs_mid_rank_pct": "0.755966",
          "signed_pct": "0.115473"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.000311",
          "abs_mid_rank_pct": "0.014627",
          "signed_pct": "0.547344"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.010771",
          "abs_mid_rank_pct": "0.428022",
          "signed_pct": "0.307929"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.010121",
          "abs_mid_rank_pct": "0.408006",
          "signed_pct": "0.727483"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "-0.005603",
          "abs_mid_rank_pct": "0.233256",
          "signed_pct": "0.415704"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.036163",
          "abs_mid_rank_pct": "0.899923",
          "signed_pct": "0.934565"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "0.024661",
          "abs_mid_rank_pct": "0.769823",
          "signed_pct": "0.877598"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.009128",
          "abs_mid_rank_pct": "0.375674",
          "signed_pct": "0.335643"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "0.003469",
          "abs_mid_rank_pct": "0.150885",
          "signed_pct": "0.608160"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.002749",
          "abs_mid_rank_pct": "0.127021",
          "signed_pct": "0.598152"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "-0.010152",
          "abs_mid_rank_pct": "0.410316",
          "signed_pct": "0.319477"
        }
      ]
    },
    {
      "cell": 8,
      "cell_key": "FOMC|5d|sar",
      "family": "FOMC",
      "horizon": "5d",
      "metric": "sar",
      "event_n": 65,
      "published": {
        "memp": "0.556582",
        "signed_percentile_median": "0.505004"
      },
      "recomputed": {
        "memp": "0.556582",
        "signed_percentile_median": "0.505004"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "fomc-policy-decision-2018-01-31",
          "anchor_session": "2018-01-31",
          "response": "1.398466",
          "abs_mid_rank_pct": "0.849885",
          "signed_pct": "0.921478"
        },
        {
          "event": "fomc-policy-decision-2018-03-21",
          "anchor_session": "2018-03-21",
          "response": "-0.895025",
          "abs_mid_rank_pct": "0.672055",
          "signed_pct": "0.172440"
        },
        {
          "event": "fomc-policy-decision-2018-05-02",
          "anchor_session": "2018-05-02",
          "response": "0.105204",
          "abs_mid_rank_pct": "0.083911",
          "signed_pct": "0.578137"
        },
        {
          "event": "fomc-policy-decision-2018-06-13",
          "anchor_session": "2018-06-13",
          "response": "0.264361",
          "abs_mid_rank_pct": "0.212471",
          "signed_pct": "0.642032"
        },
        {
          "event": "fomc-policy-decision-2018-08-01",
          "anchor_session": "2018-08-01",
          "response": "-0.232873",
          "abs_mid_rank_pct": "0.190146",
          "signed_pct": "0.441878"
        },
        {
          "event": "fomc-policy-decision-2018-09-26",
          "anchor_session": "2018-09-26",
          "response": "-0.293934",
          "abs_mid_rank_pct": "0.249423",
          "signed_pct": "0.413395"
        },
        {
          "event": "fomc-policy-decision-2018-11-08",
          "anchor_session": "2018-11-08",
          "response": "0.547903",
          "abs_mid_rank_pct": "0.458045",
          "signed_pct": "0.753657"
        },
        {
          "event": "fomc-policy-decision-2018-12-19",
          "anchor_session": "2018-12-19",
          "response": "0.548589",
          "abs_mid_rank_pct": "0.459584",
          "signed_pct": "0.754426"
        },
        {
          "event": "fomc-policy-decision-2019-01-30",
          "anchor_session": "2019-01-30",
          "response": "-0.542306",
          "abs_mid_rank_pct": "0.452656",
          "signed_pct": "0.297921"
        },
        {
          "event": "fomc-policy-decision-2019-03-20",
          "anchor_session": "2019-03-20",
          "response": "-0.971229",
          "abs_mid_rank_pct": "0.709007",
          "signed_pct": "0.149346"
        },
        {
          "event": "fomc-policy-decision-2019-05-01",
          "anchor_session": "2019-05-01",
          "response": "0.463720",
          "abs_mid_rank_pct": "0.385681",
          "signed_pct": "0.719784"
        },
        {
          "event": "fomc-policy-decision-2019-06-19",
          "anchor_session": "2019-06-19",
          "response": "0.042633",
          "abs_mid_rank_pct": "0.037721",
          "signed_pct": "0.553503"
        },
        {
          "event": "fomc-policy-decision-2019-07-31",
          "anchor_session": "2019-07-31",
          "response": "-2.400297",
          "abs_mid_rank_pct": "0.976135",
          "signed_pct": "0.013087"
        },
        {
          "event": "fomc-policy-decision-2019-09-18",
          "anchor_session": "2019-09-18",
          "response": "-0.080570",
          "abs_mid_rank_pct": "0.071594",
          "signed_pct": "0.500385"
        },
        {
          "event": "fomc-policy-decision-2019-10-30",
          "anchor_session": "2019-10-30",
          "response": "0.937487",
          "abs_mid_rank_pct": "0.695150",
          "signed_pct": "0.852964"
        },
        {
          "event": "fomc-policy-decision-2019-12-11",
          "anchor_session": "2019-12-11",
          "response": "1.212767",
          "abs_mid_rank_pct": "0.799076",
          "signed_pct": "0.900693"
        },
        {
          "event": "fomc-policy-decision-2020-01-29",
          "anchor_session": "2020-01-29",
          "response": "1.332338",
          "abs_mid_rank_pct": "0.832179",
          "signed_pct": "0.914550"
        },
        {
          "event": "fomc-policy-decision-2020-03-03",
          "anchor_session": "2020-03-03",
          "response": "-7.187391",
          "abs_mid_rank_pct": "0.997691",
          "signed_pct": "0.002309"
        },
        {
          "event": "fomc-policy-decision-2020-03-15",
          "anchor_session": "2020-03-13",
          "response": "-1.152013",
          "abs_mid_rank_pct": "0.778291",
          "signed_pct": "0.112394"
        },
        {
          "event": "fomc-policy-decision-2020-04-29",
          "anchor_session": "2020-04-29",
          "response": "-1.635810",
          "abs_mid_rank_pct": "0.898383",
          "signed_pct": "0.043880"
        },
        {
          "event": "fomc-policy-decision-2020-06-10",
          "anchor_session": "2020-06-10",
          "response": "-0.248304",
          "abs_mid_rank_pct": "0.200924",
          "signed_pct": "0.434950"
        },
        {
          "event": "fomc-policy-decision-2020-07-29",
          "anchor_session": "2020-07-29",
          "response": "-0.463464",
          "abs_mid_rank_pct": "0.385681",
          "signed_pct": "0.334103"
        },
        {
          "event": "fomc-policy-decision-2020-09-16",
          "anchor_session": "2020-09-16",
          "response": "-1.047698",
          "abs_mid_rank_pct": "0.743649",
          "signed_pct": "0.130870"
        },
        {
          "event": "fomc-policy-decision-2020-11-05",
          "anchor_session": "2020-11-05",
          "response": "1.444358",
          "abs_mid_rank_pct": "0.859892",
          "signed_pct": "0.924557"
        },
        {
          "event": "fomc-policy-decision-2020-12-16",
          "anchor_session": "2020-12-16",
          "response": "0.221237",
          "abs_mid_rank_pct": "0.179369",
          "signed_pct": "0.626636"
        },
        {
          "event": "fomc-policy-decision-2021-01-27",
          "anchor_session": "2021-01-27",
          "response": "0.401981",
          "abs_mid_rank_pct": "0.336413",
          "signed_pct": "0.701309"
        },
        {
          "event": "fomc-policy-decision-2021-03-17",
          "anchor_session": "2021-03-17",
          "response": "-1.302465",
          "abs_mid_rank_pct": "0.822171",
          "signed_pct": "0.086990"
        },
        {
          "event": "fomc-policy-decision-2021-04-28",
          "anchor_session": "2021-04-28",
          "response": "0.734395",
          "abs_mid_rank_pct": "0.591994",
          "signed_pct": "0.808314"
        },
        {
          "event": "fomc-policy-decision-2021-06-16",
          "anchor_session": "2021-06-16",
          "response": "-1.585236",
          "abs_mid_rank_pct": "0.889145",
          "signed_pct": "0.047729"
        },
        {
          "event": "fomc-policy-decision-2021-07-28",
          "anchor_session": "2021-07-28",
          "response": "-0.236466",
          "abs_mid_rank_pct": "0.192456",
          "signed_pct": "0.440339"
        },
        {
          "event": "fomc-policy-decision-2021-09-22",
          "anchor_session": "2021-09-22",
          "response": "3.427479",
          "abs_mid_rank_pct": "0.986143",
          "signed_pct": "0.993072"
        },
        {
          "event": "fomc-policy-decision-2021-11-03",
          "anchor_session": "2021-11-03",
          "response": "-0.284038",
          "abs_mid_rank_pct": "0.233256",
          "signed_pct": "0.421093"
        },
        {
          "event": "fomc-policy-decision-2021-12-15",
          "anchor_session": "2021-12-15",
          "response": "0.029150",
          "abs_mid_rank_pct": "0.023865",
          "signed_pct": "0.544265"
        },
        {
          "event": "fomc-policy-decision-2022-01-26",
          "anchor_session": "2022-01-26",
          "response": "-1.734272",
          "abs_mid_rank_pct": "0.917629",
          "signed_pct": "0.038491"
        },
        {
          "event": "fomc-policy-decision-2022-03-16",
          "anchor_session": "2022-03-16",
          "response": "-1.757838",
          "abs_mid_rank_pct": "0.922248",
          "signed_pct": "0.035412"
        },
        {
          "event": "fomc-policy-decision-2022-05-04",
          "anchor_session": "2022-05-04",
          "response": "0.108786",
          "abs_mid_rank_pct": "0.090069",
          "signed_pct": "0.581986"
        },
        {
          "event": "fomc-policy-decision-2022-06-15",
          "anchor_session": "2022-06-15",
          "response": "-0.884119",
          "abs_mid_rank_pct": "0.668206",
          "signed_pct": "0.173980"
        },
        {
          "event": "fomc-policy-decision-2022-07-27",
          "anchor_session": "2022-07-27",
          "response": "-0.968671",
          "abs_mid_rank_pct": "0.707467",
          "signed_pct": "0.150885"
        },
        {
          "event": "fomc-policy-decision-2022-09-21",
          "anchor_session": "2022-09-21",
          "response": "-1.264793",
          "abs_mid_rank_pct": "0.814473",
          "signed_pct": "0.092379"
        },
        {
          "event": "fomc-policy-decision-2022-11-02",
          "anchor_session": "2022-11-02",
          "response": "0.271379",
          "abs_mid_rank_pct": "0.217090",
          "signed_pct": "0.645112"
        },
        {
          "event": "fomc-policy-decision-2022-12-14",
          "anchor_session": "2022-12-14",
          "response": "1.316270",
          "abs_mid_rank_pct": "0.827560",
          "signed_pct": "0.912240"
        },
        {
          "event": "fomc-policy-decision-2023-02-01",
          "anchor_session": "2023-02-01",
          "response": "0.851999",
          "abs_mid_rank_pct": "0.650500",
          "signed_pct": "0.833718"
        },
        {
          "event": "fomc-policy-decision-2023-03-22",
          "anchor_session": "2023-03-22",
          "response": "-0.067847",
          "abs_mid_rank_pct": "0.061586",
          "signed_pct": "0.505004"
        },
        {
          "event": "fomc-policy-decision-2023-05-03",
          "anchor_session": "2023-05-03",
          "response": "-0.749479",
          "abs_mid_rank_pct": "0.604311",
          "signed_pct": "0.210931"
        },
        {
          "event": "fomc-policy-decision-2023-06-14",
          "anchor_session": "2023-06-14",
          "response": "-1.023439",
          "abs_mid_rank_pct": "0.735951",
          "signed_pct": "0.133949"
        },
        {
          "event": "fomc-policy-decision-2023-07-26",
          "anchor_session": "2023-07-26",
          "response": "-0.125267",
          "abs_mid_rank_pct": "0.107775",
          "signed_pct": "0.480370"
        },
        {
          "event": "fomc-policy-decision-2023-09-20",
          "anchor_session": "2023-09-20",
          "response": "0.032333",
          "abs_mid_rank_pct": "0.023865",
          "signed_pct": "0.544265"
        },
        {
          "event": "fomc-policy-decision-2023-11-01",
          "anchor_session": "2023-11-01",
          "response": "0.679338",
          "abs_mid_rank_pct": "0.556582",
          "signed_pct": "0.795227"
        },
        {
          "event": "fomc-policy-decision-2023-12-13",
          "anchor_session": "2023-12-13",
          "response": "0.318920",
          "abs_mid_rank_pct": "0.270978",
          "signed_pct": "0.675905"
        },
        {
          "event": "fomc-policy-decision-2024-01-31",
          "anchor_session": "2024-01-31",
          "response": "-2.250125",
          "abs_mid_rank_pct": "0.962279",
          "signed_pct": "0.020015"
        },
        {
          "event": "fomc-policy-decision-2024-03-20",
          "anchor_session": "2024-03-20",
          "response": "0.547171",
          "abs_mid_rank_pct": "0.457275",
          "signed_pct": "0.752887"
        },
        {
          "event": "fomc-policy-decision-2024-05-01",
          "anchor_session": "2024-05-01",
          "response": "0.182420",
          "abs_mid_rank_pct": "0.154734",
          "signed_pct": "0.615858"
        },
        {
          "event": "fomc-policy-decision-2024-06-12",
          "anchor_session": "2024-06-12",
          "response": "-0.597288",
          "abs_mid_rank_pct": "0.491147",
          "signed_pct": "0.277136"
        },
        {
          "event": "fomc-policy-decision-2024-07-31",
          "anchor_session": "2024-07-31",
          "response": "-1.297536",
          "abs_mid_rank_pct": "0.821401",
          "signed_pct": "0.087760"
        },
        {
          "event": "fomc-policy-decision-2024-09-18",
          "anchor_session": "2024-09-18",
          "response": "-1.266104",
          "abs_mid_rank_pct": "0.814473",
          "signed_pct": "0.092379"
        },
        {
          "event": "fomc-policy-decision-2024-11-07",
          "anchor_session": "2024-11-07",
          "response": "0.495936",
          "abs_mid_rank_pct": "0.414165",
          "signed_pct": "0.732871"
        },
        {
          "event": "fomc-policy-decision-2024-12-18",
          "anchor_session": "2024-12-18",
          "response": "-0.101114",
          "abs_mid_rank_pct": "0.080831",
          "signed_pct": "0.494996"
        },
        {
          "event": "fomc-policy-decision-2025-01-29",
          "anchor_session": "2025-01-29",
          "response": "0.330716",
          "abs_mid_rank_pct": "0.280216",
          "signed_pct": "0.679754"
        },
        {
          "event": "fomc-policy-decision-2025-03-19",
          "anchor_session": "2025-03-19",
          "response": "0.285372",
          "abs_mid_rank_pct": "0.235566",
          "signed_pct": "0.655889"
        },
        {
          "event": "fomc-policy-decision-2025-05-07",
          "anchor_session": "2025-05-07",
          "response": "0.673015",
          "abs_mid_rank_pct": "0.553503",
          "signed_pct": "0.793687"
        },
        {
          "event": "fomc-policy-decision-2025-06-18",
          "anchor_session": "2025-06-18",
          "response": "1.148094",
          "abs_mid_rank_pct": "0.776751",
          "signed_pct": "0.889145"
        },
        {
          "event": "fomc-policy-decision-2025-07-30",
          "anchor_session": "2025-07-30",
          "response": "-0.872248",
          "abs_mid_rank_pct": "0.662818",
          "signed_pct": "0.176289"
        },
        {
          "event": "fomc-policy-decision-2025-09-17",
          "anchor_session": "2025-09-17",
          "response": "-0.301694",
          "abs_mid_rank_pct": "0.256351",
          "signed_pct": "0.409546"
        },
        {
          "event": "fomc-policy-decision-2025-10-29",
          "anchor_session": "2025-10-29",
          "response": "0.863630",
          "abs_mid_rank_pct": "0.657429",
          "signed_pct": "0.836798"
        },
        {
          "event": "fomc-policy-decision-2025-12-10",
          "anchor_session": "2025-12-10",
          "response": "0.825367",
          "abs_mid_rank_pct": "0.639723",
          "signed_pct": "0.829099"
        }
      ]
    },
    {
      "cell": 9,
      "cell_key": "OPEC|1d|raw_return",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "raw_return",
      "event_n": 32,
      "published": {
        "memp": "0.529164",
        "signed_percentile_median": "0.406463"
      },
      "recomputed": {
        "memp": "0.529164",
        "signed_percentile_median": "0.406463"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.026297",
          "abs_mid_rank_pct": "0.776668",
          "signed_pct": "0.109301"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.032340",
          "abs_mid_rank_pct": "0.853389",
          "signed_pct": "0.071992"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.002287",
          "abs_mid_rank_pct": "0.089858",
          "signed_pct": "0.438255"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.006595",
          "abs_mid_rank_pct": "0.267998",
          "signed_pct": "0.623752"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.009638",
          "abs_mid_rank_pct": "0.375197",
          "signed_pct": "0.675775"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "0.127119",
          "abs_mid_rank_pct": "0.998949",
          "signed_pct": "0.998949"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.084445",
          "abs_mid_rank_pct": "0.991592",
          "signed_pct": "0.994220"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.038841",
          "abs_mid_rank_pct": "0.907514",
          "signed_pct": "0.953757"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.048270",
          "abs_mid_rank_pct": "0.949553",
          "signed_pct": "0.025749"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.040816",
          "abs_mid_rank_pct": "0.919075",
          "signed_pct": "0.042564"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "0.011896",
          "abs_mid_rank_pct": "0.449291",
          "signed_pct": "0.719390"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "-0.046600",
          "abs_mid_rank_pct": "0.943773",
          "signed_pct": "0.028902"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.014747",
          "abs_mid_rank_pct": "0.531792",
          "signed_pct": "0.233841"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.014549",
          "abs_mid_rank_pct": "0.526537",
          "signed_pct": "0.763006"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "0.049299",
          "abs_mid_rank_pct": "0.951130",
          "signed_pct": "0.976353"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "-0.013967",
          "abs_mid_rank_pct": "0.513925",
          "signed_pct": "0.243826"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "0.007971",
          "abs_mid_rank_pct": "0.318970",
          "signed_pct": "0.652128"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "-0.010191",
          "abs_mid_rank_pct": "0.391487",
          "signed_pct": "0.296374"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.028816",
          "abs_mid_rank_pct": "0.812401",
          "signed_pct": "0.092486"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "-0.015629",
          "abs_mid_rank_pct": "0.563847",
          "signed_pct": "0.213873"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.019020",
          "abs_mid_rank_pct": "0.644246",
          "signed_pct": "0.816080"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.022737",
          "abs_mid_rank_pct": "0.721492",
          "signed_pct": "0.134524"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "-0.005619",
          "abs_mid_rank_pct": "0.226484",
          "signed_pct": "0.374672"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.106730",
          "abs_mid_rank_pct": "0.996322",
          "signed_pct": "0.000525"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "-0.017312",
          "abs_mid_rank_pct": "0.605360",
          "signed_pct": "0.189175"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.013133",
          "abs_mid_rank_pct": "0.487126",
          "signed_pct": "0.744088"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.010993",
          "abs_mid_rank_pct": "0.416185",
          "signed_pct": "0.284813"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.003153",
          "abs_mid_rank_pct": "0.118234",
          "signed_pct": "0.543878"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.007328",
          "abs_mid_rank_pct": "0.299527",
          "signed_pct": "0.343142"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "0.007208",
          "abs_mid_rank_pct": "0.294798",
          "signed_pct": "0.638991"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.006624",
          "abs_mid_rank_pct": "0.268523",
          "signed_pct": "0.624277"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.007909",
          "abs_mid_rank_pct": "0.317919",
          "signed_pct": "0.651603"
        }
      ]
    },
    {
      "cell": 10,
      "cell_key": "OPEC|1d|spy_relative_ar",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "spy_relative_ar",
      "event_n": 32,
      "published": {
        "memp": "0.523384",
        "signed_percentile_median": "0.493431"
      },
      "recomputed": {
        "memp": "0.523384",
        "signed_percentile_median": "0.493431"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.012684",
          "abs_mid_rank_pct": "0.529164",
          "signed_pct": "0.237520"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.034237",
          "abs_mid_rank_pct": "0.911718",
          "signed_pct": "0.042564"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.010281",
          "abs_mid_rank_pct": "0.434051",
          "signed_pct": "0.288492"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.009739",
          "abs_mid_rank_pct": "0.414083",
          "signed_pct": "0.714661"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.018768",
          "abs_mid_rank_pct": "0.695744",
          "signed_pct": "0.851813"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "0.115031",
          "abs_mid_rank_pct": "0.999475",
          "signed_pct": "0.999475"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.075827",
          "abs_mid_rank_pct": "0.997898",
          "signed_pct": "0.997898"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.032863",
          "abs_mid_rank_pct": "0.904362",
          "signed_pct": "0.950079"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.062623",
          "abs_mid_rank_pct": "0.992118",
          "signed_pct": "0.002627"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.026048",
          "abs_mid_rank_pct": "0.822911",
          "signed_pct": "0.086705"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "0.028307",
          "abs_mid_rank_pct": "0.858644",
          "signed_pct": "0.930110"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "-0.045925",
          "abs_mid_rank_pct": "0.967945",
          "signed_pct": "0.014188"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.010974",
          "abs_mid_rank_pct": "0.463479",
          "signed_pct": "0.271676"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.024865",
          "abs_mid_rank_pct": "0.809774",
          "signed_pct": "0.904362"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "0.045488",
          "abs_mid_rank_pct": "0.966369",
          "signed_pct": "0.981083"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "-0.012051",
          "abs_mid_rank_pct": "0.501314",
          "signed_pct": "0.251182"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "0.002055",
          "abs_mid_rank_pct": "0.097740",
          "signed_pct": "0.567525"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "-0.009119",
          "abs_mid_rank_pct": "0.391487",
          "signed_pct": "0.313190"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.029631",
          "abs_mid_rank_pct": "0.875460",
          "signed_pct": "0.061482"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "0.001201",
          "abs_mid_rank_pct": "0.058854",
          "signed_pct": "0.550709"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.021174",
          "abs_mid_rank_pct": "0.750394",
          "signed_pct": "0.877036"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.024633",
          "abs_mid_rank_pct": "0.805045",
          "signed_pct": "0.096164"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.006218",
          "abs_mid_rank_pct": "0.283762",
          "signed_pct": "0.655281"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.048187",
          "abs_mid_rank_pct": "0.973200",
          "signed_pct": "0.011035"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "-0.011577",
          "abs_mid_rank_pct": "0.489228",
          "signed_pct": "0.256963"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.007500",
          "abs_mid_rank_pct": "0.333158",
          "signed_pct": "0.678928"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.003541",
          "abs_mid_rank_pct": "0.170257",
          "signed_pct": "0.436153"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "-0.012047",
          "abs_mid_rank_pct": "0.501314",
          "signed_pct": "0.251182"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.009785",
          "abs_mid_rank_pct": "0.416185",
          "signed_pct": "0.299002"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "0.003621",
          "abs_mid_rank_pct": "0.172359",
          "signed_pct": "0.606936"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.004747",
          "abs_mid_rank_pct": "0.218077",
          "signed_pct": "0.627956"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.012475",
          "abs_mid_rank_pct": "0.517604",
          "signed_pct": "0.763006"
        }
      ]
    },
    {
      "cell": 11,
      "cell_key": "OPEC|1d|sector_relative_ar",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "sector_relative_ar",
      "event_n": 32,
      "published": {
        "memp": "0.472149",
        "signed_percentile_median": "0.461377"
      },
      "recomputed": {
        "memp": "0.472149",
        "signed_percentile_median": "0.461377"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.006204",
          "abs_mid_rank_pct": "0.528114",
          "signed_pct": "0.240673"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.016732",
          "abs_mid_rank_pct": "0.916448",
          "signed_pct": "0.040462"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.006271",
          "abs_mid_rank_pct": "0.531792",
          "signed_pct": "0.239622"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.007767",
          "abs_mid_rank_pct": "0.631634",
          "signed_pct": "0.819758"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.012882",
          "abs_mid_rank_pct": "0.834997",
          "signed_pct": "0.919075"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "0.082070",
          "abs_mid_rank_pct": "1.000000",
          "signed_pct": "1.000000"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.029942",
          "abs_mid_rank_pct": "0.987388",
          "signed_pct": "0.991592"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.008332",
          "abs_mid_rank_pct": "0.662112",
          "signed_pct": "0.838676"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.024418",
          "abs_mid_rank_pct": "0.979506",
          "signed_pct": "0.006306"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.005484",
          "abs_mid_rank_pct": "0.476090",
          "signed_pct": "0.268523"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "-0.001349",
          "abs_mid_rank_pct": "0.122438",
          "signed_pct": "0.461377"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "-0.009514",
          "abs_mid_rank_pct": "0.719916",
          "signed_pct": "0.143458"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.005493",
          "abs_mid_rank_pct": "0.476090",
          "signed_pct": "0.268523"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "-0.003229",
          "abs_mid_rank_pct": "0.292696",
          "signed_pct": "0.371519"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "0.004025",
          "abs_mid_rank_pct": "0.366264",
          "signed_pct": "0.694167"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "-0.007335",
          "abs_mid_rank_pct": "0.596427",
          "signed_pct": "0.207042"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "0.002769",
          "abs_mid_rank_pct": "0.250657",
          "signed_pct": "0.647399"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.000481",
          "abs_mid_rank_pct": "0.043090",
          "signed_pct": "0.546506"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.002636",
          "abs_mid_rank_pct": "0.236469",
          "signed_pct": "0.404099"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "-0.003114",
          "abs_mid_rank_pct": "0.278508",
          "signed_pct": "0.380452"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.001526",
          "abs_mid_rank_pct": "0.137152",
          "signed_pct": "0.591172"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.005780",
          "abs_mid_rank_pct": "0.497635",
          "signed_pct": "0.257488"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.004059",
          "abs_mid_rank_pct": "0.368366",
          "signed_pct": "0.695218"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.014731",
          "abs_mid_rank_pct": "0.885970",
          "signed_pct": "0.055702"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.000742",
          "abs_mid_rank_pct": "0.067262",
          "signed_pct": "0.557541"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.000008",
          "abs_mid_rank_pct": "0.001051",
          "signed_pct": "0.522859"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.001341",
          "abs_mid_rank_pct": "0.122438",
          "signed_pct": "0.461377"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.005373",
          "abs_mid_rank_pct": "0.468208",
          "signed_pct": "0.743037"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.005039",
          "abs_mid_rank_pct": "0.447714",
          "signed_pct": "0.286915"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "0.002259",
          "abs_mid_rank_pct": "0.206516",
          "signed_pct": "0.630058"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.006510",
          "abs_mid_rank_pct": "0.544404",
          "signed_pct": "0.776668"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "-0.001709",
          "abs_mid_rank_pct": "0.160273",
          "signed_pct": "0.442459"
        }
      ]
    },
    {
      "cell": 12,
      "cell_key": "OPEC|1d|sar",
      "family": "OPEC",
      "horizon": "1d",
      "metric": "sar",
      "event_n": 32,
      "published": {
        "memp": "0.602733",
        "signed_percentile_median": "0.492643"
      },
      "recomputed": {
        "memp": "0.602733",
        "signed_percentile_median": "0.492643"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.817273",
          "abs_mid_rank_pct": "0.615870",
          "signed_pct": "0.196006"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-2.274722",
          "abs_mid_rank_pct": "0.973200",
          "signed_pct": "0.014188"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.580034",
          "abs_mid_rank_pct": "0.459800",
          "signed_pct": "0.274829"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.420139",
          "abs_mid_rank_pct": "0.339464",
          "signed_pct": "0.682081"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.348099",
          "abs_mid_rank_pct": "0.282712",
          "signed_pct": "0.653705"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "2.967364",
          "abs_mid_rank_pct": "0.994220",
          "signed_pct": "0.996322"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "2.252637",
          "abs_mid_rank_pct": "0.970573",
          "signed_pct": "0.985286"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.930803",
          "abs_mid_rank_pct": "0.680504",
          "signed_pct": "0.843931"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-2.341049",
          "abs_mid_rank_pct": "0.976353",
          "signed_pct": "0.013137"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-1.100848",
          "abs_mid_rank_pct": "0.754073",
          "signed_pct": "0.124015"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "1.239171",
          "abs_mid_rank_pct": "0.800315",
          "signed_pct": "0.900683"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "-1.566040",
          "abs_mid_rank_pct": "0.888071",
          "signed_pct": "0.059380"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.362342",
          "abs_mid_rank_pct": "0.290068",
          "signed_pct": "0.367840"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.972368",
          "abs_mid_rank_pct": "0.698371",
          "signed_pct": "0.850236"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "2.469589",
          "abs_mid_rank_pct": "0.981608",
          "signed_pct": "0.992118"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "-0.686637",
          "abs_mid_rank_pct": "0.536521",
          "signed_pct": "0.233841"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "0.130394",
          "abs_mid_rank_pct": "0.113505",
          "signed_pct": "0.574882"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "-0.660774",
          "abs_mid_rank_pct": "0.515502",
          "signed_pct": "0.240673"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-2.988776",
          "abs_mid_rank_pct": "0.994745",
          "signed_pct": "0.001576"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "0.090823",
          "abs_mid_rank_pct": "0.076721",
          "signed_pct": "0.557541"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "1.461219",
          "abs_mid_rank_pct": "0.866001",
          "signed_pct": "0.933789"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-1.602736",
          "abs_mid_rank_pct": "0.894903",
          "signed_pct": "0.055176"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.415345",
          "abs_mid_rank_pct": "0.336311",
          "signed_pct": "0.681030"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-3.047780",
          "abs_mid_rank_pct": "0.995796",
          "signed_pct": "0.001051"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "-0.634520",
          "abs_mid_rank_pct": "0.500263",
          "signed_pct": "0.250657"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.437297",
          "abs_mid_rank_pct": "0.353127",
          "signed_pct": "0.685759"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.213112",
          "abs_mid_rank_pct": "0.185497",
          "signed_pct": "0.427746"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "-0.773645",
          "abs_mid_rank_pct": "0.589595",
          "signed_pct": "0.206516"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.626820",
          "abs_mid_rank_pct": "0.496059",
          "signed_pct": "0.253284"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "0.246233",
          "abs_mid_rank_pct": "0.212296",
          "signed_pct": "0.626379"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.325591",
          "abs_mid_rank_pct": "0.261692",
          "signed_pct": "0.645822"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.820987",
          "abs_mid_rank_pct": "0.616395",
          "signed_pct": "0.812401"
        }
      ]
    },
    {
      "cell": 13,
      "cell_key": "OPEC|5d|raw_return",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "raw_return",
      "event_n": 32,
      "published": {
        "memp": "0.469957",
        "signed_percentile_median": "0.597180"
      },
      "recomputed": {
        "memp": "0.469957",
        "signed_percentile_median": "0.597180"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "0.011035",
          "abs_mid_rank_pct": "0.215205",
          "signed_pct": "0.580012"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.077679",
          "abs_mid_rank_pct": "0.885346",
          "signed_pct": "0.057020"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "0.021341",
          "abs_mid_rank_pct": "0.370325",
          "signed_pct": "0.663397"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.024965",
          "abs_mid_rank_pct": "0.421827",
          "signed_pct": "0.692213"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.020722",
          "abs_mid_rank_pct": "0.359902",
          "signed_pct": "0.659105"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-0.089297",
          "abs_mid_rank_pct": "0.920294",
          "signed_pct": "0.039240"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.132445",
          "abs_mid_rank_pct": "0.982219",
          "signed_pct": "0.988351"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.124164",
          "abs_mid_rank_pct": "0.975475",
          "signed_pct": "0.984672"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.082632",
          "abs_mid_rank_pct": "0.903740",
          "signed_pct": "0.048437"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.001701",
          "abs_mid_rank_pct": "0.033722",
          "signed_pct": "0.458614"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "0.036063",
          "abs_mid_rank_pct": "0.573268",
          "signed_pct": "0.773758"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.015001",
          "abs_mid_rank_pct": "0.279583",
          "signed_pct": "0.614347"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "0.019663",
          "abs_mid_rank_pct": "0.346413",
          "signed_pct": "0.651134"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "-0.018063",
          "abs_mid_rank_pct": "0.328633",
          "signed_pct": "0.312078"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "0.042402",
          "abs_mid_rank_pct": "0.644390",
          "signed_pct": "0.814224"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.027693",
          "abs_mid_rank_pct": "0.458001",
          "signed_pct": "0.712446"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.052753",
          "abs_mid_rank_pct": "0.746168",
          "signed_pct": "0.125077"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.005763",
          "abs_mid_rank_pct": "0.103617",
          "signed_pct": "0.525445"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.041513",
          "abs_mid_rank_pct": "0.635193",
          "signed_pct": "0.175353"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "-0.029885",
          "abs_mid_rank_pct": "0.481913",
          "signed_pct": "0.242183"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.082650",
          "abs_mid_rank_pct": "0.903740",
          "signed_pct": "0.952177"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.013671",
          "abs_mid_rank_pct": "0.261189",
          "signed_pct": "0.342735"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "-0.016296",
          "abs_mid_rank_pct": "0.302882",
          "signed_pct": "0.320049"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.126151",
          "abs_mid_rank_pct": "0.976701",
          "signed_pct": "0.009197"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.033841",
          "abs_mid_rank_pct": "0.543225",
          "signed_pct": "0.756591"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.030782",
          "abs_mid_rank_pct": "0.497241",
          "signed_pct": "0.731453"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "0.030193",
          "abs_mid_rank_pct": "0.486818",
          "signed_pct": "0.725322"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "-0.005740",
          "abs_mid_rank_pct": "0.103004",
          "signed_pct": "0.422440"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "0.003780",
          "abs_mid_rank_pct": "0.065604",
          "signed_pct": "0.507051"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-0.069300",
          "abs_mid_rank_pct": "0.849172",
          "signed_pct": "0.074188"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.020975",
          "abs_mid_rank_pct": "0.362968",
          "signed_pct": "0.659718"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.019922",
          "abs_mid_rank_pct": "0.350705",
          "signed_pct": "0.654200"
        }
      ]
    },
    {
      "cell": 14,
      "cell_key": "OPEC|5d|spy_relative_ar",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "spy_relative_ar",
      "event_n": 32,
      "published": {
        "memp": "0.584304",
        "signed_percentile_median": "0.625996"
      },
      "recomputed": {
        "memp": "0.584304",
        "signed_percentile_median": "0.625996"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "0.023629",
          "abs_mid_rank_pct": "0.424893",
          "signed_pct": "0.733906"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.065918",
          "abs_mid_rank_pct": "0.868792",
          "signed_pct": "0.063765"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "0.013987",
          "abs_mid_rank_pct": "0.268547",
          "signed_pct": "0.651134"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.017184",
          "abs_mid_rank_pct": "0.323115",
          "signed_pct": "0.681177"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "-0.009616",
          "abs_mid_rank_pct": "0.189454",
          "signed_pct": "0.427345"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-0.041918",
          "abs_mid_rank_pct": "0.680564",
          "signed_pct": "0.166769"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.132335",
          "abs_mid_rank_pct": "0.991416",
          "signed_pct": "0.994482"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.104128",
          "abs_mid_rank_pct": "0.975475",
          "signed_pct": "0.981606"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.109791",
          "abs_mid_rank_pct": "0.978541",
          "signed_pct": "0.006131"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.021639",
          "abs_mid_rank_pct": "0.396076",
          "signed_pct": "0.323115"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "0.074277",
          "abs_mid_rank_pct": "0.912324",
          "signed_pct": "0.953403"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.001634",
          "abs_mid_rank_pct": "0.028817",
          "signed_pct": "0.536481"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.028089",
          "abs_mid_rank_pct": "0.505825",
          "signed_pct": "0.264868"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.036381",
          "abs_mid_rank_pct": "0.623544",
          "signed_pct": "0.825874"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "0.041864",
          "abs_mid_rank_pct": "0.679951",
          "signed_pct": "0.846720"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.023066",
          "abs_mid_rank_pct": "0.418761",
          "signed_pct": "0.730227"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.056763",
          "abs_mid_rank_pct": "0.814224",
          "signed_pct": "0.092581"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.007967",
          "abs_mid_rank_pct": "0.158798",
          "signed_pct": "0.600858"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.054104",
          "abs_mid_rank_pct": "0.790926",
          "signed_pct": "0.106070"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "-0.047134",
          "abs_mid_rank_pct": "0.732679",
          "signed_pct": "0.140405"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.035106",
          "abs_mid_rank_pct": "0.603924",
          "signed_pct": "0.817903"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.009830",
          "abs_mid_rank_pct": "0.193133",
          "signed_pct": "0.424893"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.023429",
          "abs_mid_rank_pct": "0.423053",
          "signed_pct": "0.732679"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.103569",
          "abs_mid_rank_pct": "0.975475",
          "signed_pct": "0.006131"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.038111",
          "abs_mid_rank_pct": "0.641324",
          "signed_pct": "0.830779"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.014240",
          "abs_mid_rank_pct": "0.272839",
          "signed_pct": "0.654200"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "0.032943",
          "abs_mid_rank_pct": "0.564684",
          "signed_pct": "0.798896"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "-0.030606",
          "abs_mid_rank_pct": "0.537094",
          "signed_pct": "0.251380"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.011933",
          "abs_mid_rank_pct": "0.232373",
          "signed_pct": "0.405886"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-0.045107",
          "abs_mid_rank_pct": "0.709381",
          "signed_pct": "0.150828"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.037234",
          "abs_mid_rank_pct": "0.631514",
          "signed_pct": "0.828939"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.016557",
          "abs_mid_rank_pct": "0.313305",
          "signed_pct": "0.677498"
        }
      ]
    },
    {
      "cell": 15,
      "cell_key": "OPEC|5d|sector_relative_ar",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "sector_relative_ar",
      "event_n": 32,
      "published": {
        "memp": "0.428878",
        "signed_percentile_median": "0.565604"
      },
      "recomputed": {
        "memp": "0.428878",
        "signed_percentile_median": "0.565604"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "0.000523",
          "abs_mid_rank_pct": "0.022685",
          "signed_pct": "0.521153"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.046775",
          "abs_mid_rank_pct": "0.967505",
          "signed_pct": "0.019620"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "0.000784",
          "abs_mid_rank_pct": "0.034335",
          "signed_pct": "0.526671"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.015086",
          "abs_mid_rank_pct": "0.589209",
          "signed_pct": "0.814838"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.019543",
          "abs_mid_rank_pct": "0.702636",
          "signed_pct": "0.870632"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "0.022656",
          "abs_mid_rank_pct": "0.763948",
          "signed_pct": "0.908032"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.052767",
          "abs_mid_rank_pct": "0.980380",
          "signed_pct": "0.990803"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.026332",
          "abs_mid_rank_pct": "0.813611",
          "signed_pct": "0.923973"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.040493",
          "abs_mid_rank_pct": "0.941140",
          "signed_pct": "0.034948"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "0.001586",
          "abs_mid_rank_pct": "0.061925",
          "signed_pct": "0.541999"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "0.014555",
          "abs_mid_rank_pct": "0.576947",
          "signed_pct": "0.808093"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.003310",
          "abs_mid_rank_pct": "0.131821",
          "signed_pct": "0.581239"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.006851",
          "abs_mid_rank_pct": "0.278357",
          "signed_pct": "0.381361"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "-0.007199",
          "abs_mid_rank_pct": "0.293685",
          "signed_pct": "0.374617"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "0.008235",
          "abs_mid_rank_pct": "0.347639",
          "signed_pct": "0.695892"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.009795",
          "abs_mid_rank_pct": "0.418761",
          "signed_pct": "0.730840"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.014565",
          "abs_mid_rank_pct": "0.576947",
          "signed_pct": "0.231147"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "-0.006057",
          "abs_mid_rank_pct": "0.251380",
          "signed_pct": "0.392397"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.007071",
          "abs_mid_rank_pct": "0.286327",
          "signed_pct": "0.378296"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "-0.007038",
          "abs_mid_rank_pct": "0.285714",
          "signed_pct": "0.378909"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.017673",
          "abs_mid_rank_pct": "0.667689",
          "signed_pct": "0.852238"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "0.017866",
          "abs_mid_rank_pct": "0.671980",
          "signed_pct": "0.854690"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "-0.019257",
          "abs_mid_rank_pct": "0.698345",
          "signed_pct": "0.169834"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.013631",
          "abs_mid_rank_pct": "0.547517",
          "signed_pct": "0.252606"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.028352",
          "abs_mid_rank_pct": "0.839362",
          "signed_pct": "0.936849"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.007723",
          "abs_mid_rank_pct": "0.326793",
          "signed_pct": "0.684243"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "0.006063",
          "abs_mid_rank_pct": "0.251380",
          "signed_pct": "0.643777"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.001971",
          "abs_mid_rank_pct": "0.076640",
          "signed_pct": "0.549969"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.010414",
          "abs_mid_rank_pct": "0.438994",
          "signed_pct": "0.304108"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-0.027797",
          "abs_mid_rank_pct": "0.831392",
          "signed_pct": "0.100552"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.004975",
          "abs_mid_rank_pct": "0.204169",
          "signed_pct": "0.621091"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.004555",
          "abs_mid_rank_pct": "0.187615",
          "signed_pct": "0.610668"
        }
      ]
    },
    {
      "cell": 16,
      "cell_key": "OPEC|5d|sar",
      "family": "OPEC",
      "horizon": "5d",
      "metric": "sar",
      "event_n": 32,
      "published": {
        "memp": "0.580012",
        "signed_percentile_median": "0.639485"
      },
      "recomputed": {
        "memp": "0.580012",
        "signed_percentile_median": "0.639485"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "0.680869",
          "abs_mid_rank_pct": "0.509503",
          "signed_pct": "0.768853"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-1.958616",
          "abs_mid_rank_pct": "0.946658",
          "signed_pct": "0.028817"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "0.352903",
          "abs_mid_rank_pct": "0.276517",
          "signed_pct": "0.663397"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.331525",
          "abs_mid_rank_pct": "0.261189",
          "signed_pct": "0.652974"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "-0.079757",
          "abs_mid_rank_pct": "0.068670",
          "signed_pct": "0.488044"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-0.483584",
          "abs_mid_rank_pct": "0.380748",
          "signed_pct": "0.330472"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "1.758159",
          "abs_mid_rank_pct": "0.919068",
          "signed_pct": "0.964439"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "1.318976",
          "abs_mid_rank_pct": "0.818516",
          "signed_pct": "0.914776"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-1.835499",
          "abs_mid_rank_pct": "0.931330",
          "signed_pct": "0.035561"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.408971",
          "abs_mid_rank_pct": "0.325567",
          "signed_pct": "0.356836"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "1.454130",
          "abs_mid_rank_pct": "0.855303",
          "signed_pct": "0.934396"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.024911",
          "abs_mid_rank_pct": "0.014715",
          "signed_pct": "0.530963"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.414757",
          "abs_mid_rank_pct": "0.329859",
          "signed_pct": "0.354997"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.636259",
          "abs_mid_rank_pct": "0.486205",
          "signed_pct": "0.759657"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "1.016447",
          "abs_mid_rank_pct": "0.700797",
          "signed_pct": "0.855917"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.587721",
          "abs_mid_rank_pct": "0.451257",
          "signed_pct": "0.746781"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-1.610604",
          "abs_mid_rank_pct": "0.894543",
          "signed_pct": "0.056407"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.258167",
          "abs_mid_rank_pct": "0.207848",
          "signed_pct": "0.625996"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-2.440538",
          "abs_mid_rank_pct": "0.978541",
          "signed_pct": "0.012876"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "-1.593440",
          "abs_mid_rank_pct": "0.892091",
          "signed_pct": "0.057633"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "1.083446",
          "abs_mid_rank_pct": "0.733906",
          "signed_pct": "0.874310"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.286047",
          "abs_mid_rank_pct": "0.231147",
          "signed_pct": "0.406499"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.699923",
          "abs_mid_rank_pct": "0.524831",
          "signed_pct": "0.776824"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-2.929504",
          "abs_mid_rank_pct": "0.995095",
          "signed_pct": "0.002452"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.934101",
          "abs_mid_rank_pct": "0.659718",
          "signed_pct": "0.840589"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.371327",
          "abs_mid_rank_pct": "0.290619",
          "signed_pct": "0.665236"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "0.886603",
          "abs_mid_rank_pct": "0.636419",
          "signed_pct": "0.829552"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "-0.879003",
          "abs_mid_rank_pct": "0.635193",
          "signed_pct": "0.194359"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.341876",
          "abs_mid_rank_pct": "0.269160",
          "signed_pct": "0.389945"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-1.371585",
          "abs_mid_rank_pct": "0.832005",
          "signed_pct": "0.089516"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "1.142120",
          "abs_mid_rank_pct": "0.759044",
          "signed_pct": "0.884120"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "0.487306",
          "abs_mid_rank_pct": "0.383200",
          "signed_pct": "0.712446"
        }
      ]
    },
    {
      "cell": 17,
      "cell_key": "OPEC|20d|raw_return",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "raw_return",
      "event_n": 32,
      "published": {
        "memp": "0.420135",
        "signed_percentile_median": "0.553431"
      },
      "recomputed": {
        "memp": "0.420135",
        "signed_percentile_median": "0.553431"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.006809",
          "abs_mid_rank_pct": "0.058493",
          "signed_pct": "0.457818"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.050223",
          "abs_mid_rank_pct": "0.398200",
          "signed_pct": "0.286839"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.046113",
          "abs_mid_rank_pct": "0.367829",
          "signed_pct": "0.303712"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.158034",
          "abs_mid_rank_pct": "0.877390",
          "signed_pct": "0.928009"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.291325",
          "abs_mid_rank_pct": "0.993251",
          "signed_pct": "0.993251"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-0.178274",
          "abs_mid_rank_pct": "0.928009",
          "signed_pct": "0.021372"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.054747",
          "abs_mid_rank_pct": "0.421822",
          "signed_pct": "0.697413"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.107291",
          "abs_mid_rank_pct": "0.713161",
          "signed_pct": "0.839145"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.062646",
          "abs_mid_rank_pct": "0.483690",
          "signed_pct": "0.239595"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.025389",
          "abs_mid_rank_pct": "0.208099",
          "signed_pct": "0.386952"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "-0.238415",
          "abs_mid_rank_pct": "0.984252",
          "signed_pct": "0.001125"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.102185",
          "abs_mid_rank_pct": "0.687289",
          "signed_pct": "0.825647"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.059783",
          "abs_mid_rank_pct": "0.469066",
          "signed_pct": "0.246344"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.048426",
          "abs_mid_rank_pct": "0.384702",
          "signed_pct": "0.677165"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "-0.010737",
          "abs_mid_rank_pct": "0.095613",
          "signed_pct": "0.443195"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.048408",
          "abs_mid_rank_pct": "0.384702",
          "signed_pct": "0.677165"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.000322",
          "abs_mid_rank_pct": "0.004499",
          "signed_pct": "0.479190"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.102070",
          "abs_mid_rank_pct": "0.687289",
          "signed_pct": "0.825647"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.035100",
          "abs_mid_rank_pct": "0.275591",
          "signed_pct": "0.355456"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "0.073000",
          "abs_mid_rank_pct": "0.545557",
          "signed_pct": "0.751406"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.112030",
          "abs_mid_rank_pct": "0.735658",
          "signed_pct": "0.851519"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.020715",
          "abs_mid_rank_pct": "0.176603",
          "signed_pct": "0.406074"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.063478",
          "abs_mid_rank_pct": "0.488189",
          "signed_pct": "0.724409"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.037753",
          "abs_mid_rank_pct": "0.300337",
          "signed_pct": "0.340832"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.053676",
          "abs_mid_rank_pct": "0.418448",
          "signed_pct": "0.696288"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.058194",
          "abs_mid_rank_pct": "0.447694",
          "signed_pct": "0.703037"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.042347",
          "abs_mid_rank_pct": "0.348706",
          "signed_pct": "0.314961"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.075263",
          "abs_mid_rank_pct": "0.561305",
          "signed_pct": "0.762655"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "0.034388",
          "abs_mid_rank_pct": "0.272216",
          "signed_pct": "0.627672"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-0.047827",
          "abs_mid_rank_pct": "0.383577",
          "signed_pct": "0.293588"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.065132",
          "abs_mid_rank_pct": "0.502812",
          "signed_pct": "0.728909"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "-0.049521",
          "abs_mid_rank_pct": "0.393701",
          "signed_pct": "0.289089"
        }
      ]
    },
    {
      "cell": 18,
      "cell_key": "OPEC|20d|spy_relative_ar",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "spy_relative_ar",
      "event_n": 32,
      "published": {
        "memp": "0.402137",
        "signed_percentile_median": "0.547807"
      },
      "recomputed": {
        "memp": "0.402137",
        "signed_percentile_median": "0.547807"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.026683",
          "abs_mid_rank_pct": "0.188976",
          "signed_pct": "0.451069"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.030112",
          "abs_mid_rank_pct": "0.210349",
          "signed_pct": "0.438695"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.049485",
          "abs_mid_rank_pct": "0.368954",
          "signed_pct": "0.343082"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.128032",
          "abs_mid_rank_pct": "0.824522",
          "signed_pct": "0.885264"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.240138",
          "abs_mid_rank_pct": "0.987627",
          "signed_pct": "0.987627"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-0.175472",
          "abs_mid_rank_pct": "0.934758",
          "signed_pct": "0.015748"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.044733",
          "abs_mid_rank_pct": "0.334083",
          "signed_pct": "0.696288"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.078960",
          "abs_mid_rank_pct": "0.577053",
          "signed_pct": "0.793026"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.104308",
          "abs_mid_rank_pct": "0.719910",
          "signed_pct": "0.120360"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.059190",
          "abs_mid_rank_pct": "0.443195",
          "signed_pct": "0.290214"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "-0.155751",
          "abs_mid_rank_pct": "0.897638",
          "signed_pct": "0.024747"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.148681",
          "abs_mid_rank_pct": "0.883015",
          "signed_pct": "0.913386"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "0.001721",
          "abs_mid_rank_pct": "0.012373",
          "signed_pct": "0.554556"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.054313",
          "abs_mid_rank_pct": "0.399325",
          "signed_pct": "0.719910"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "-0.025686",
          "abs_mid_rank_pct": "0.181102",
          "signed_pct": "0.455568"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.007469",
          "abs_mid_rank_pct": "0.048369",
          "signed_pct": "0.571429"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.045977",
          "abs_mid_rank_pct": "0.341957",
          "signed_pct": "0.358830"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.080754",
          "abs_mid_rank_pct": "0.588301",
          "signed_pct": "0.796400"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.072511",
          "abs_mid_rank_pct": "0.533183",
          "signed_pct": "0.239595"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "0.036699",
          "abs_mid_rank_pct": "0.263217",
          "signed_pct": "0.665917"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.054959",
          "abs_mid_rank_pct": "0.404949",
          "signed_pct": "0.723285"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.005392",
          "abs_mid_rank_pct": "0.037120",
          "signed_pct": "0.529809"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "0.102359",
          "abs_mid_rank_pct": "0.707537",
          "signed_pct": "0.832396"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-0.093762",
          "abs_mid_rank_pct": "0.658043",
          "signed_pct": "0.159730"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.007889",
          "abs_mid_rank_pct": "0.050619",
          "signed_pct": "0.572553"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.006807",
          "abs_mid_rank_pct": "0.043870",
          "signed_pct": "0.570304"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.036558",
          "abs_mid_rank_pct": "0.260967",
          "signed_pct": "0.403825"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.037738",
          "abs_mid_rank_pct": "0.274466",
          "signed_pct": "0.668166"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.002423",
          "abs_mid_rank_pct": "0.015748",
          "signed_pct": "0.541057"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-0.067028",
          "abs_mid_rank_pct": "0.485939",
          "signed_pct": "0.268841"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.067756",
          "abs_mid_rank_pct": "0.490439",
          "signed_pct": "0.755906"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "-0.059021",
          "abs_mid_rank_pct": "0.443195",
          "signed_pct": "0.290214"
        }
      ]
    },
    {
      "cell": 19,
      "cell_key": "OPEC|20d|sector_relative_ar",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "sector_relative_ar",
      "event_n": 32,
      "published": {
        "memp": "0.449381",
        "signed_percentile_median": "0.539370"
      },
      "recomputed": {
        "memp": "0.449381",
        "signed_percentile_median": "0.539370"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "0.001042",
          "abs_mid_rank_pct": "0.019123",
          "signed_pct": "0.537683"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.014835",
          "abs_mid_rank_pct": "0.251969",
          "signed_pct": "0.408324"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.045315",
          "abs_mid_rank_pct": "0.696288",
          "signed_pct": "0.179978"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "0.100841",
          "abs_mid_rank_pct": "0.984252",
          "signed_pct": "0.991001"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.147709",
          "abs_mid_rank_pct": "1.000000",
          "signed_pct": "1.000000"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-0.024176",
          "abs_mid_rank_pct": "0.410574",
          "signed_pct": "0.326209"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.056364",
          "abs_mid_rank_pct": "0.799775",
          "signed_pct": "0.919010"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.054845",
          "abs_mid_rank_pct": "0.789651",
          "signed_pct": "0.915636"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.044360",
          "abs_mid_rank_pct": "0.681665",
          "signed_pct": "0.188976"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.040590",
          "abs_mid_rank_pct": "0.650169",
          "signed_pct": "0.208099"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "-0.069227",
          "abs_mid_rank_pct": "0.888639",
          "signed_pct": "0.069741"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "0.020487",
          "abs_mid_rank_pct": "0.345332",
          "signed_pct": "0.708661"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "-0.021759",
          "abs_mid_rank_pct": "0.367829",
          "signed_pct": "0.350956"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "-0.046389",
          "abs_mid_rank_pct": "0.709786",
          "signed_pct": "0.173228"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "-0.026915",
          "abs_mid_rank_pct": "0.460067",
          "signed_pct": "0.302587"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.021166",
          "abs_mid_rank_pct": "0.356580",
          "signed_pct": "0.715411"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.001093",
          "abs_mid_rank_pct": "0.020247",
          "signed_pct": "0.517435"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "0.001788",
          "abs_mid_rank_pct": "0.029246",
          "signed_pct": "0.541057"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-0.021499",
          "abs_mid_rank_pct": "0.364454",
          "signed_pct": "0.354331"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "0.004316",
          "abs_mid_rank_pct": "0.073116",
          "signed_pct": "0.560180"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.038305",
          "abs_mid_rank_pct": "0.616423",
          "signed_pct": "0.839145"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "0.031013",
          "abs_mid_rank_pct": "0.526434",
          "signed_pct": "0.800900"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "-0.008929",
          "abs_mid_rank_pct": "0.163105",
          "signed_pct": "0.444319"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "0.017123",
          "abs_mid_rank_pct": "0.286839",
          "signed_pct": "0.676040"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.046113",
          "abs_mid_rank_pct": "0.701912",
          "signed_pct": "0.878515"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.009501",
          "abs_mid_rank_pct": "0.175478",
          "signed_pct": "0.609674"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.025801",
          "abs_mid_rank_pct": "0.438695",
          "signed_pct": "0.314961"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.019181",
          "abs_mid_rank_pct": "0.330709",
          "signed_pct": "0.700787"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "0.007960",
          "abs_mid_rank_pct": "0.145107",
          "signed_pct": "0.601800"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-0.039054",
          "abs_mid_rank_pct": "0.627672",
          "signed_pct": "0.217098"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "0.028935",
          "abs_mid_rank_pct": "0.490439",
          "signed_pct": "0.782902"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "-0.044554",
          "abs_mid_rank_pct": "0.685039",
          "signed_pct": "0.187852"
        }
      ]
    },
    {
      "cell": 20,
      "cell_key": "OPEC|20d|sar",
      "family": "OPEC",
      "horizon": "20d",
      "metric": "sar",
      "event_n": 32,
      "published": {
        "memp": "0.383577",
        "signed_percentile_median": "0.544432"
      },
      "recomputed": {
        "memp": "0.383577",
        "signed_percentile_median": "0.544432"
      },
      "reconciled": true,
      "rows": [
        {
          "event": "opec-2018-06-23-conformity-return",
          "anchor_session": "2018-06-22",
          "response": "-0.384424",
          "abs_mid_rank_pct": "0.226097",
          "signed_pct": "0.427447"
        },
        {
          "event": "opec-2018-12-07-cut-1p2",
          "anchor_session": "2018-12-07",
          "response": "-0.447357",
          "abs_mid_rank_pct": "0.267717",
          "signed_pct": "0.404949"
        },
        {
          "event": "opec-2019-07-02-extension",
          "anchor_session": "2019-07-02",
          "response": "-0.624258",
          "abs_mid_rank_pct": "0.384702",
          "signed_pct": "0.335208"
        },
        {
          "event": "opec-2019-12-06-deepen-1p7",
          "anchor_session": "2019-12-06",
          "response": "1.235039",
          "abs_mid_rank_pct": "0.705287",
          "signed_pct": "0.845894"
        },
        {
          "event": "opec-2020-04-12-cut-9p7",
          "anchor_session": "2020-04-09",
          "response": "0.995911",
          "abs_mid_rank_pct": "0.590551",
          "signed_pct": "0.796400"
        },
        {
          "event": "opec-2020-06-06-extension",
          "anchor_session": "2020-06-05",
          "response": "-1.012157",
          "abs_mid_rank_pct": "0.596175",
          "signed_pct": "0.202475"
        },
        {
          "event": "opec-2020-12-03-restoration-start",
          "anchor_session": "2020-12-03",
          "response": "0.297155",
          "abs_mid_rank_pct": "0.169854",
          "signed_pct": "0.629921"
        },
        {
          "event": "opec-2021-01-05-feb-mar-levels",
          "anchor_session": "2021-01-05",
          "response": "0.500088",
          "abs_mid_rank_pct": "0.301462",
          "signed_pct": "0.686164"
        },
        {
          "event": "opec-2021-04-01-gradual-return",
          "anchor_session": "2021-04-01",
          "response": "-0.871918",
          "abs_mid_rank_pct": "0.525309",
          "signed_pct": "0.246344"
        },
        {
          "event": "opec-2021-07-18-monthly-400k",
          "anchor_session": "2021-07-16",
          "response": "-0.559349",
          "abs_mid_rank_pct": "0.343082",
          "signed_pct": "0.356580"
        },
        {
          "event": "opec-2022-06-02-accelerate-648k",
          "anchor_session": "2022-06-02",
          "response": "-1.524580",
          "abs_mid_rank_pct": "0.809899",
          "signed_pct": "0.082115"
        },
        {
          "event": "opec-2022-08-03-sep-100k",
          "anchor_session": "2022-08-03",
          "response": "1.133696",
          "abs_mid_rank_pct": "0.649044",
          "signed_pct": "0.822272"
        },
        {
          "event": "opec-2022-09-05-oct-minus-100k",
          "anchor_session": "2022-09-02",
          "response": "0.012703",
          "abs_mid_rank_pct": "0.007874",
          "signed_pct": "0.552306"
        },
        {
          "event": "opec-2022-10-05-cut-2mbd",
          "anchor_session": "2022-10-05",
          "response": "0.474940",
          "abs_mid_rank_pct": "0.290214",
          "signed_pct": "0.680540"
        },
        {
          "event": "opec-2023-04-02-voluntary-1p16",
          "anchor_session": "2023-03-31",
          "response": "-0.311825",
          "abs_mid_rank_pct": "0.177728",
          "signed_pct": "0.455568"
        },
        {
          "event": "opec-2023-06-04-2024-levels",
          "anchor_session": "2023-06-02",
          "response": "0.095155",
          "abs_mid_rank_pct": "0.046119",
          "signed_pct": "0.570304"
        },
        {
          "event": "opec-2023-11-30-voluntary-2p2",
          "anchor_session": "2023-11-30",
          "response": "-0.652281",
          "abs_mid_rank_pct": "0.391451",
          "signed_pct": "0.332958"
        },
        {
          "event": "opec-2024-03-03-q2-extension",
          "anchor_session": "2024-03-01",
          "response": "1.308462",
          "abs_mid_rank_pct": "0.734533",
          "signed_pct": "0.860517"
        },
        {
          "event": "opec-2024-06-02-extension-schedule",
          "anchor_session": "2024-05-31",
          "response": "-1.635423",
          "abs_mid_rank_pct": "0.843645",
          "signed_pct": "0.069741"
        },
        {
          "event": "opec-2024-09-05-two-month-delay",
          "anchor_session": "2024-09-05",
          "response": "0.620338",
          "abs_mid_rank_pct": "0.382452",
          "signed_pct": "0.718785"
        },
        {
          "event": "opec-2024-11-03-one-month-delay",
          "anchor_session": "2024-11-01",
          "response": "0.848087",
          "abs_mid_rank_pct": "0.511811",
          "signed_pct": "0.768279"
        },
        {
          "event": "opec-2024-12-05-april-start",
          "anchor_session": "2024-12-05",
          "response": "-0.078446",
          "abs_mid_rank_pct": "0.039370",
          "signed_pct": "0.527559"
        },
        {
          "event": "opec-2025-03-03-activation",
          "anchor_session": "2025-03-03",
          "response": "1.528974",
          "abs_mid_rank_pct": "0.809899",
          "signed_pct": "0.892013"
        },
        {
          "event": "opec-2025-04-03-may-411k",
          "anchor_session": "2025-04-03",
          "response": "-1.326061",
          "abs_mid_rank_pct": "0.739033",
          "signed_pct": "0.125984"
        },
        {
          "event": "opec-2025-05-03-jun-411k",
          "anchor_session": "2025-05-02",
          "response": "0.096679",
          "abs_mid_rank_pct": "0.047244",
          "signed_pct": "0.571429"
        },
        {
          "event": "opec-2025-06-01-jul-411k",
          "anchor_session": "2025-05-30",
          "response": "0.088756",
          "abs_mid_rank_pct": "0.043870",
          "signed_pct": "0.569179"
        },
        {
          "event": "opec-2025-07-05-aug-548k",
          "anchor_session": "2025-07-03",
          "response": "-0.491945",
          "abs_mid_rank_pct": "0.298088",
          "signed_pct": "0.386952"
        },
        {
          "event": "opec-2025-08-03-sep-547k",
          "anchor_session": "2025-08-01",
          "response": "0.541910",
          "abs_mid_rank_pct": "0.328459",
          "signed_pct": "0.692913"
        },
        {
          "event": "opec-2025-09-07-oct-137k",
          "anchor_session": "2025-09-05",
          "response": "-0.034705",
          "abs_mid_rank_pct": "0.021372",
          "signed_pct": "0.536558"
        },
        {
          "event": "opec-2025-10-05-nov-137k",
          "anchor_session": "2025-10-03",
          "response": "-1.019081",
          "abs_mid_rank_pct": "0.600675",
          "signed_pct": "0.199100"
        },
        {
          "event": "opec-2025-11-02-dec-137k-pause",
          "anchor_session": "2025-10-31",
          "response": "1.039174",
          "abs_mid_rank_pct": "0.608549",
          "signed_pct": "0.803150"
        },
        {
          "event": "opec-2025-11-30-2026-hold",
          "anchor_session": "2025-11-28",
          "response": "-0.868561",
          "abs_mid_rank_pct": "0.524184",
          "signed_pct": "0.247469"
        }
      ]
    }
  ]
};
