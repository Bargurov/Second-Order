"""Tests for the Mission I research contract (mission-i-evidence-v1).

Contract under test:

* the structured summary is built at request time by PARSING the seven
  tracked Mission I publications - no events.db, no price cache, no
  provider, no network, and no hand-copied research number anywhere in
  the module;
* nothing is recomputed: no MEMP, no calibration, no placement draw, no
  falsifier perturbation - repeated copies across publications are
  reconciled, never re-derived;
* the 20-cell primary surface keeps its frozen family/horizon/metric
  order, exact-precision decimal strings, the approved two-part state
  object (no Mission-J-style scalar node state), and both attempted and
  available denominators;
* FOMC and OPEC stay separate ledgers (no pooled 97 anywhere); FOMC 20d
  appears only as a structurally-infeasible universe row, never a cell;
* nulls, knife-edge fragility, mixed results, and the whole-mission
  conclusion WITH its not-a-hypothesis-test clarifier are first-class;
* artifact drift fails loudly with no partial payload, and the endpoint
  maps drift to a stable sanitized 503.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import mission_i_evidence as mie  # noqa: E402

STATS = ROOT / "stats"
SOURCES = {
    "i0_protocol": STATS / "I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md",
    "i1_universe": STATS / "I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md",
    "i2a_substrate": STATS / "I2A_RESPONSE_SUBSTRATE.md",
    "i2b_memp": STATS / "I2B_MEMP_PRIMARY_COMPARISON.md",
    "i2c_calibration": STATS / "I2C_CALIBRATION.md",
    "i2c_falsifiers": STATS / "I2C_FALSIFIERS.md",
    "closeout": STATS / "MISSION_I_CLOSEOUT.md",
}

EXPECTED_SECTIONS = [
    "calibration", "constitution", "contract_version", "falsifiers",
    "family_horizon_readout", "fragility", "non_claims", "primary_cells",
    "provenance", "universe", "unresolved_or_limits",
    "whole_mission_conclusion",
]

METRICS = ("raw_return", "spy_relative_ar", "sector_relative_ar", "sar")
EXPECTED_KEYS = [
    f"{fam}|{h}|{m}"
    for fam, hs in (("FOMC", ("1d", "5d")), ("OPEC", ("1d", "5d", "20d")))
    for h in hs
    for m in METRICS
]

BANNED_KEY_FRAGMENTS = ("score", "rank", "strength", "winner",
                        "probabilit", "combined", "pooled", "supports")


def _build(**kwargs):
    return mie.build_mission_i_evidence_summary(**kwargs)


_CACHE: dict = {}


def _payload():
    if "p" not in _CACHE:
        _CACHE["p"] = _build()
    return _CACHE["p"]


def _tampered(path: Path, old: str, new: str, td: str) -> Path:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture precondition missing: {old!r}"
    bad = Path(td) / path.name
    bad.write_text(text.replace(old, new), encoding="utf-8")
    return bad


def _all_keys(obj, out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k).lower())
            _all_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _all_keys(v, out)
    return out


def _all_ints(obj, out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for v in obj.values():
            _all_ints(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _all_ints(v, out)
    elif isinstance(obj, int) and not isinstance(obj, bool):
        out.append(obj)
    return out


# ---------------------------------------------------------------------------
# Contract shape (protections 1-3)
# ---------------------------------------------------------------------------


class ContractShapeTests(unittest.TestCase):
    def test_1_contract_version(self):
        self.assertEqual(_payload()["contract_version"],
                         "mission-i-evidence-v1")

    def test_2_exact_top_level_sections(self):
        self.assertEqual(sorted(_payload()), EXPECTED_SECTIONS)

    def test_3_seven_provenance_sources_with_live_hashes(self):
        prov = _payload()["provenance"]
        self.assertEqual(sorted(prov["sources"]), sorted(SOURCES))
        for key, path in SOURCES.items():
            src = prov["sources"][key]
            self.assertEqual(src["artifact"], f"stats/{path.name}")
            self.assertEqual(
                src["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(src["bytes"], path.stat().st_size)
        self.assertIn("I0", prov["publication_chain"])
        self.assertIn("closeout", prov["publication_chain"].lower())
        self.assertIn("computes no", prov["no_recompute_statement"])
        vers = prov["publication_versions"]
        self.assertEqual(vers["i0_protocol"], "i0-v1")
        self.assertEqual(vers["i2b_memp"], "i2b-memp-primary-v1")
        self.assertEqual(vers["i2c_falsifiers"], "i2c-falsifiers-v1")

    def test_3b_canonical_reproduction_commands_exposed(self):
        # I2A's tracked "## Reproduction" section is the only canonically
        # recorded reproduction path in the seven publications; the
        # contract must expose it PARSED (never hand-copied in the module)
        # together with the tracked fresh-clone reproducibility limit.
        repro = _payload()["provenance"]["reproduction"]
        self.assertEqual(repro["commands"], [
            "python -m scripts.i2a_response_substrate --emit",
            "python -m unittest tests.test_i2a_response_substrate",
        ])
        self.assertEqual(repro["source"], "stats/I2A_RESPONSE_SUBSTRATE.md")
        self.assertIn("not claimed", repro["reproducibility_limits"])

    def test_3c_untracked_provenance_is_honestly_null(self):
        # No Mission I publication records a computation date or an
        # execution commit; the contract must say so explicitly rather
        # than inferring one from the current checkout.
        prov = _payload()["provenance"]
        self.assertIn("computation_dates", prov)
        self.assertIn("execution_commits", prov)
        self.assertIsNone(prov["computation_dates"])
        self.assertIsNone(prov["execution_commits"])


# ---------------------------------------------------------------------------
# Universe and denominators (protections 4-6, 27)
# ---------------------------------------------------------------------------


class UniverseTests(unittest.TestCase):
    def test_4_two_family_ledgers_in_frozen_order(self):
        fams = _payload()["universe"]["families"]
        self.assertEqual([f["family"] for f in fams], ["FOMC", "OPEC"])
        fomc, opec = fams
        self.assertEqual((fomc["primary"], fomc["market_benchmark"],
                          fomc["sector_benchmark"]), ("KRE", "SPY", "XLF"))
        self.assertEqual((opec["primary"], opec["market_benchmark"],
                          opec["sector_benchmark"]), ("XOP", "SPY", "XLE"))
        self.assertEqual(fomc["study_event_n_attempted"], 65)
        self.assertEqual(fomc["study_event_n_available"], 65)
        self.assertEqual(opec["study_event_n_attempted"], 32)
        self.assertEqual(opec["study_event_n_available"], 32)
        for f in fams:
            self.assertEqual(f["joint_sessions"], 2385)
            self.assertEqual(f["era_sessions"], 2011)
            self.assertIn("adjusted", f["price_basis_policy"])
        reg = opec["exclusion"]["register"]
        self.assertEqual(reg["name"],
                         "opec-known-date-exclusion-register@i0-v1")
        self.assertEqual(reg["calendar_dates"], 41)
        self.assertEqual(reg["anchor_sessions"], 39)

    def test_5_six_universe_horizon_rows_with_funnels(self):
        fams = _payload()["universe"]["families"]
        rows = [(f["family"], h) for f in fams for h in f["horizons"]]
        self.assertEqual(len(rows), 6)
        fomc_h = {h["horizon"]: h for h in fams[0]["horizons"]}
        opec_h = {h["horizon"]: h for h in fams[1]["horizons"]}
        self.assertEqual(list(fomc_h), ["1d", "5d", "20d"])
        self.assertEqual(list(opec_h), ["1d", "5d", "20d"])
        self.assertEqual(fomc_h["1d"]["reference_n_available"], 1816)
        self.assertEqual(fomc_h["1d"]["funnel"]["exclusion_cut"], 195)
        self.assertEqual(fomc_h["1d"]["non_overlapping_reference_n"], 927)
        self.assertEqual(fomc_h["5d"]["reference_n_available"], 1299)
        self.assertEqual(fomc_h["5d"]["non_overlapping_reference_n"], 233)
        self.assertEqual(opec_h["1d"]["reference_n_available"], 1903)
        self.assertEqual(opec_h["5d"]["reference_n_available"], 1631)
        self.assertEqual(opec_h["20d"]["reference_n_available"], 889)
        self.assertEqual(opec_h["20d"]["non_overlapping_reference_n"], 51)
        for h in list(fomc_h.values()) + list(opec_h.values()):
            self.assertEqual(h["reference_n_attempted"],
                             h["reference_n_available"])
        self.assertIn("not", _payload()["universe"]["blocks_note"])
        self.assertIn("sample size",
                      _payload()["universe"]["blocks_note"])

    def test_6_fomc_20d_structural_infeasibility(self):
        fomc_h = {h["horizon"]: h
                  for h in _payload()["universe"]["families"][0]["horizons"]}
        row = fomc_h["20d"]
        self.assertEqual(row["reference_n_available"], 0)
        self.assertEqual(row["reference_n_attempted"], 0)
        self.assertEqual(row["non_overlapping_reference_n"], 0)
        self.assertEqual(row["status"], "structurally_infeasible")
        self.assertIn("not a data gap", row["limitation"])
        # ... and no fabricated cell or readout exists for it
        keys = [c["cell_key"] for c in _payload()["primary_cells"]]
        self.assertNotIn("FOMC|20d|raw_return", keys)
        readouts = [(r["family"], r["horizon"])
                    for r in _payload()["family_horizon_readout"]]
        self.assertNotIn(("FOMC", "20d"), readouts)

    def test_27_no_pooled_family_denominator(self):
        self.assertNotIn(97, _all_ints(_payload()))
        prohibition = _payload()["constitution"][
            "family_pooling_prohibition"].lower()
        self.assertIn("never pooled", prohibition)


# ---------------------------------------------------------------------------
# Primary 20-cell surface (protections 7-14)
# ---------------------------------------------------------------------------


class PrimaryCellTests(unittest.TestCase):
    def test_7_exactly_20_primary_cells(self):
        self.assertEqual(len(_payload()["primary_cells"]), 20)
        self.assertEqual(_payload()["constitution"]["primary_cell_count"],
                         20)

    def test_8_frozen_family_horizon_metric_order(self):
        cells = _payload()["primary_cells"]
        self.assertEqual([c["cell"] for c in cells], list(range(1, 21)))
        self.assertEqual([c["cell_key"] for c in cells], EXPECTED_KEYS)

    def test_9_event_and_reference_attempted_available(self):
        for c in _payload()["primary_cells"]:
            expected_n = 65 if c["family"] == "FOMC" else 32
            self.assertEqual(c["event_n_attempted"], expected_n, c["cell_key"])
            self.assertEqual(c["event_n_available"], expected_n)
            self.assertEqual(c["reference_n_attempted"],
                             c["reference_n_available"])
            self.assertGreater(c["reference_n_available"], 0)

    def test_10_exact_first_cell_values(self):
        c = _payload()["primary_cells"][0]
        self.assertEqual(c["cell_key"], "FOMC|1d|raw_return")
        self.assertEqual(c["reference_n_available"], 1816)
        self.assertEqual(c["memp"], "0.674559")
        self.assertEqual(c["signed_percentile_median"], "0.339207")
        self.assertEqual(c["calibration_percentile"], "0.997000")
        self.assertEqual(c["state"],
                         {"memp_direction": "above_ordinary_midpoint",
                          "f6_position": "outside"})
        self.assertEqual(c["f1_loyo"], {"runs": 8, "flips": 0})
        self.assertEqual(c["f2_loeo"], {"runs": 65, "flips": 0})
        self.assertEqual(c["f3_overlap_decimation"], {
            "original_reference_n": 1816, "canonical_reference_n": 927,
            "decimated_memp": "0.666667", "change": "-0.007893",
            "sign_flip": False})

    def test_11_exact_fomc_5d_raw_knife_edge_values(self):
        c = next(x for x in _payload()["primary_cells"]
                 if x["cell_key"] == "FOMC|5d|raw_return")
        self.assertEqual(c["memp"], "0.501155")
        self.assertEqual(c["calibration_percentile"], "0.476500")
        self.assertEqual(c["state"],
                         {"memp_direction": "above_ordinary_midpoint",
                          "f6_position": "inside"})
        self.assertEqual(c["f1_loyo"], {"runs": 8, "flips": 5})
        self.assertEqual(c["f2_loeo"], {"runs": 65, "flips": 32})
        self.assertEqual(c["f3_overlap_decimation"]["sign_flip"], False)
        self.assertEqual(c["f3_overlap_decimation"]["change"], "+0.005283")

    def test_12_exact_opec_20d_cells(self):
        cells = [c for c in _payload()["primary_cells"]
                 if c["family"] == "OPEC" and c["horizon"] == "20d"]
        self.assertEqual([c["memp"] for c in cells],
                         ["0.420135", "0.402137", "0.449381", "0.383577"])
        for c in cells:
            self.assertEqual(c["state"]["memp_direction"],
                             "below_ordinary_midpoint")
            self.assertEqual(c["reference_n_available"], 889)
            self.assertEqual(c["f1_loyo"]["flips"], 0)
            self.assertEqual(c["f2_loeo"], {"runs": 32, "flips": 0})
        by_metric = {c["metric"]: c for c in cells}
        self.assertEqual(
            by_metric["sector_relative_ar"]["calibration_percentile"],
            "0.034500")
        self.assertEqual(by_metric["sar"]["calibration_percentile"],
                         "0.049500")
        self.assertEqual(
            by_metric["sector_relative_ar"]["state"]["f6_position"],
            "outside")

    def test_13_approved_two_field_state_object(self):
        for c in _payload()["primary_cells"]:
            self.assertEqual(sorted(c["state"]),
                             ["f6_position", "memp_direction"])
            self.assertIn(c["state"]["memp_direction"],
                          ("above_ordinary_midpoint",
                           "below_ordinary_midpoint",
                           "at_ordinary_midpoint"))
            self.assertIn(c["state"]["f6_position"], ("inside", "outside"))

    def test_14_no_scalar_mission_j_style_node_state(self):
        blob = json.dumps(_payload())
        for banned in ("ELEVATED", "ORDINARY_UNRESOLVED",
                       "LOWER_MAGNITUDE", "DISCORDANT", "node_state",
                       "PROPAGATED"):
            self.assertNotIn(banned, blob, banned)


# ---------------------------------------------------------------------------
# Constitution and signed diagnostic (protection 15)
# ---------------------------------------------------------------------------


class ConstitutionTests(unittest.TestCase):
    def test_15_signed_diagnostic_disclosure(self):
        d = _payload()["constitution"]["signed_percentile_disclosure"]
        joined = " ".join(d["disclaimers"]).lower()
        self.assertIn("subordinate", d["status"].lower())
        self.assertIn("not", joined)
        self.assertIn("calibrated", joined)
        self.assertIn("directional", joined)
        for c in _payload()["primary_cells"]:
            self.assertIn("signed_percentile_median", c)

    def test_15b_constitution_core_fields(self):
        cst = _payload()["constitution"]
        self.assertEqual(cst["protocol_version"], "i0-v1")
        self.assertIn("ordinary", cst["frozen_question"].lower())
        self.assertIn("MEMP", cst["estimand"]["definition"])
        self.assertEqual(cst["estimand"]["name"], "MEMP")
        self.assertEqual(cst["estimand"]["ordinary_reference_midpoint"],
                         "0.5")
        self.assertEqual(cst["evidence_class"],
                         {"descriptive": True, "comparative": True,
                          "frozen_before_outcome_comparison": True})


# ---------------------------------------------------------------------------
# Calibration (protections 16-17)
# ---------------------------------------------------------------------------


class CalibrationTests(unittest.TestCase):
    def test_16_five_completed_calibration_groups(self):
        cal = _payload()["calibration"]
        groups = cal["groups"]
        self.assertEqual([(g["family"], g["horizon"]) for g in groups],
                         [("FOMC", "1d"), ("FOMC", "5d"), ("OPEC", "1d"),
                          ("OPEC", "5d"), ("OPEC", "20d")])
        for g in groups:
            self.assertEqual(g["expected_placements"], 2000)
            self.assertEqual(g["completed_placements"], 2000)
        self.assertEqual(groups[0]["per_year_event_counts"]["2020"], 9)
        self.assertEqual(groups[2]["per_year_event_counts"]["2025"], 10)
        self.assertIn("no failure", cal["no_failure_statement"])

    def test_17_b_and_seed_parsed_with_ceiling(self):
        cal = _payload()["calibration"]
        self.assertEqual(cal["placements_per_group"], 2000)
        self.assertEqual(cal["seed"], 20180101)
        ceiling = cal["interpretation_ceiling"].lower()
        for token in ("no p-values", "no significance threshold",
                      "no confidence interval", "no new fdr pool"):
            self.assertIn(token, ceiling)
        method = cal["method"].lower()
        self.assertIn("without replacement", method)
        self.assertIn("all four metrics", method)
        self.assertIn("observed external", method)


# ---------------------------------------------------------------------------
# Falsifiers (protections 18-24)
# ---------------------------------------------------------------------------


class FalsifierTests(unittest.TestCase):
    def test_18_six_separate_definitions(self):
        defs = _payload()["falsifiers"]["definitions"]
        self.assertEqual(sorted(defs), ["f1", "f2", "f3", "f4", "f5", "f6"])
        self.assertIn("leave-one-year-out", defs["f1"])
        self.assertIn("one event at a time", defs["f2"])
        self.assertIn("non-overlapping", defs["f3"])
        self.assertIn("cross-metric", defs["f4"])
        self.assertIn("cross-horizon", defs["f5"])
        self.assertIn("central 50", defs["f6"])
        self.assertIn("stand separately",
                      _payload()["falsifiers"]["battery_disclosure"])

    def test_19_f1_totals_and_affected_cells(self):
        f1 = _payload()["falsifiers"]["f1_loyo"]
        self.assertEqual(f1["flips_total"], 10)
        self.assertEqual(f1["runs_total"], 160)
        affected = {c["cell_key"]: c["flips"] for c in f1["affected_cells"]}
        self.assertEqual(affected, {
            "FOMC|5d|raw_return": 5, "FOMC|5d|sar": 1,
            "OPEC|1d|raw_return": 1, "OPEC|1d|spy_relative_ar": 2,
            "OPEC|5d|sector_relative_ar": 1})

    def test_20_f2_totals_and_single_affected_cell(self):
        f2 = _payload()["falsifiers"]["f2_loeo"]
        self.assertEqual(f2["flips_total"], 32)
        self.assertEqual(f2["runs_total"], 904)
        self.assertEqual([c["cell_key"] for c in f2["affected_cells"]],
                         ["FOMC|5d|raw_return"])
        self.assertIn("knife-edge", f2["knife_edge_explanation"])

    def test_21_f3_zero_of_twenty(self):
        f3 = _payload()["falsifiers"]["f3_overlap_decimation"]
        self.assertEqual(f3["sign_flips"], 0)
        self.assertEqual(f3["of_cells"], 20)
        self.assertIn("not an independence proof", f3["limitation"])

    def test_22_f6_surface_totals(self):
        f6 = _payload()["falsifiers"]["f6_calibration_position"]
        self.assertEqual(f6["inside"], 9)
        self.assertEqual(f6["outside"], 11)
        self.assertEqual(f6["outside_upper"], 8)
        self.assertEqual(f6["outside_lower"], 3)
        self.assertIn("not a significance test", f6["limitation"])

    def test_23_five_ordered_f4_rows(self):
        rows = _payload()["falsifiers"]["f4_cross_metric"]
        self.assertEqual([(r["family"], r["horizon"]) for r in rows],
                         [("FOMC", "1d"), ("FOMC", "5d"), ("OPEC", "1d"),
                          ("OPEC", "5d"), ("OPEC", "20d")])
        self.assertEqual((rows[0]["positive"], rows[0]["zero"],
                          rows[0]["negative"]), (4, 0, 0))
        self.assertEqual((rows[4]["positive"], rows[4]["negative"]), (0, 4))
        self.assertEqual(rows[1]["signs"]["sector_relative_ar"], -1)

    def test_24_eight_ordered_f5_rows_with_knife_edge_caveat(self):
        rows = _payload()["falsifiers"]["f5_cross_horizon"]
        self.assertEqual(len(rows), 8)
        self.assertEqual([r["family"] for r in rows],
                         ["FOMC"] * 4 + ["OPEC"] * 4)
        fomc_raw = rows[0]
        self.assertEqual(fomc_raw["metric"], "raw_return")
        self.assertIs(fomc_raw["agree"], True)
        self.assertIn("knife-edge", fomc_raw["caveat"])
        self.assertIsNone(fomc_raw["signs"]["20d"])
        opec_sector = next(r for r in rows if r["family"] == "OPEC"
                           and r["metric"] == "sector_relative_ar")
        self.assertIs(opec_sector["agree"], True)
        self.assertEqual(sum(1 for r in rows if r["agree"]), 4)

    def test_24b_f5_caveat_paragraph_bounded_no_section_or_table_spill(self):
        """The knife-edge caveat is the closeout's blank-line paragraph —
        never a flattened-document punctuation scan that splices the
        preceding section heading and F4/F5 tables into the quoted field,
        and never a first-period truncation that drops the paragraph's
        qualifying sentences."""
        caveat = _payload()["falsifiers"]["f5_cross_horizon"][0]["caveat"]
        # no section spillover
        self.assertNotIn("###", caveat)
        self.assertNotIn("Cross-surface synthesis", caveat)
        # no table spillover (headers, separators, or rows)
        self.assertNotIn("|", caveat)
        # starts at the caveat itself and keeps the full frozen paragraph
        self.assertTrue(caveat.startswith("Caveat on FOMC raw-return"),
                        caveat[:80])
        self.assertIn("decided by a hair", caveat)
        self.assertTrue(caveat.endswith("not converted into a score."),
                        caveat[-80:])

    def test_24c_f5_caveat_boundary_survives_adjacent_structure(self):
        """Temporary-artifact-copy proof of the boundary rule: content in
        the paragraph ABOVE the caveat (here a sentinel table row) must
        never be spliced into the extracted caveat."""
        target = 'Caveat on FOMC raw-return "agree": formal sign agreement'
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(
                SOURCES["closeout"], target,
                "| SENTINEL | injected | row |\n\n" + target, td)
            payload = _build(closeout_path=bad)
        caveat = payload["falsifiers"]["f5_cross_horizon"][0]["caveat"]
        self.assertNotIn("SENTINEL", caveat)


# ---------------------------------------------------------------------------
# Readout, fragility, conclusion, non-claims (protections 25-26)
# ---------------------------------------------------------------------------


class ReadoutAndCeilingTests(unittest.TestCase):
    def test_25_conclusion_with_adjacent_clarifier(self):
        wmc = _payload()["whole_mission_conclusion"]
        self.assertIn("rejects the blanket idea", wmc["statement"])
        self.assertIn("family-, horizon-, and metric-specific",
                      wmc["statement"])
        self.assertIn("not a formal hypothesis test", wmc["clarifier"])
        self.assertIn("no p-value", wmc["clarifier"])

    def test_25b_five_family_horizon_readouts_in_order(self):
        rows = _payload()["family_horizon_readout"]
        self.assertEqual([(r["family"], r["horizon"]) for r in rows],
                         [("FOMC", "1d"), ("FOMC", "5d"), ("OPEC", "1d"),
                          ("OPEC", "5d"), ("OPEC", "20d")])
        self.assertIn("broad, perturbation-stable elevation",
                      rows[0]["headline"])
        self.assertIn("does not extend into a coherent 5d effect",
                      rows[1]["headline"])
        self.assertIn("do not show a uniform cross-metric",
                      rows[2]["headline"])
        self.assertIn("explicitly metric-dependent", rows[3]["headline"])
        self.assertIn("descriptively lower in magnitude",
                      rows[4]["headline"])

    def test_25c_fragility_record(self):
        fr = _payload()["fragility"]
        ke = fr["knife_edge"]
        self.assertEqual(ke["cell_key"], "FOMC|5d|raw_return")
        self.assertEqual(ke["memp"], "0.501155")
        self.assertEqual(ke["calibration_percentile"], "0.476500")
        self.assertEqual(ke["f1_loyo"], {"runs": 8, "flips": 5})
        self.assertEqual(ke["f2_loeo"], {"runs": 65, "flips": 32})
        self.assertIn("knife-edge", ke["explanation"])
        self.assertEqual(len(fr["loyo_affected_cells"]), 5)

    def test_26_permanent_non_claims(self):
        nc = " ".join(_payload()["non_claims"]).lower()
        for token in ("causality", "prediction", "tradeability", "alpha",
                      "single-event significance",
                      "cross-family comparability",
                      "alternative primary assets", "rolling beta",
                      "anticipation", "collisions", "mechanism causality"):
            self.assertIn(token, nc, token)
        self.assertGreaterEqual(len(_payload()["non_claims"]), 11)
        limits = " ".join(_payload()["unresolved_or_limits"]).lower()
        self.assertIn("multiple-comparison", limits)


# ---------------------------------------------------------------------------
# Structure honesty (protection 28)
# ---------------------------------------------------------------------------


class StructureHonestyTests(unittest.TestCase):
    def test_28_no_score_rank_strength_winner_probability_keys(self):
        keys = _all_keys(_payload())
        for fragment in BANNED_KEY_FRAGMENTS:
            self.assertFalse(any(fragment in k for k in keys),
                             f"banned key fragment {fragment!r}")

    def test_28b_no_assertive_claim_vocabulary(self):
        dumped = json.dumps(_payload()).lower()
        for banned in ("validated", "mechanism confirmed", "winner",
                       "strongest", "top finding"):
            self.assertNotIn(banned, dumped, banned)
        for banned in (r"\bproven\b", r"\bbuy\b", r"\bsell\b",
                       r"\bpredictive\b", r"\btradeable\b"):
            self.assertIsNone(re.search(banned, dumped), banned)


# ---------------------------------------------------------------------------
# Determinism and read-only boundary (protections 29-31)
# ---------------------------------------------------------------------------


class BoundaryTests(unittest.TestCase):
    def test_29_deterministic_repeated_build(self):
        self.assertEqual(_build(), copy.deepcopy(_build()))

    def test_30_tracked_sources_byte_identical_after_build(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in SOURCES.values()}
        _build()
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in SOURCES.values()}
        self.assertEqual(before, after)

    def test_31_no_db_provider_or_network_import(self):
        src = Path(mie.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for banned in ("db", "sqlite3", "urllib", "requests", "httpx",
                       "socket", "market_data", "market_check", "yfinance",
                       "price_cache", "numpy", "statistics", "scripts",
                       "event_study_validation"):
            self.assertNotIn(banned, imported, banned)

    def test_31b_no_network_call_during_build(self):
        import socket

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("network call during mission-i build")

        saved = socket.socket
        socket.socket = boom
        try:
            payload = _build()
        finally:
            socket.socket = saved
        self.assertEqual(payload["contract_version"],
                         "mission-i-evidence-v1")

    def test_31c_no_hardcoded_research_numbers_in_module(self):
        body = re.sub(r'("""[\s\S]*?"""|#[^\n]*)', "",
                      Path(mie.__file__).read_text(encoding="utf-8"))
        for banned in (r"\b1816\b", r"\b1299\b", r"\b1903\b", r"\b1631\b",
                       r"\b889\b", r"\b927\b", r"\b233\b", r"\b960\b",
                       r"\b287\b", r"\b904\b", r"\b160\b", r"\b2000\b",
                       r"\b20180101\b", r"\b65\b", r"\b32\b",
                       r"0\.674559", r"0\.501155"):
            self.assertIsNone(re.search(banned, body),
                              f"hardcoded research number {banned}")


# ---------------------------------------------------------------------------
# Drift refusal (protections 32-35, 38)
# ---------------------------------------------------------------------------


class DriftTests(unittest.TestCase):
    def test_32_missing_artifact_refusal(self):
        with self.assertRaises(ValueError):
            _build(i2b_path=STATS / "DOES_NOT_EXIST.md")

    def test_33_identity_and_order_drift_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(SOURCES["i2b_memp"],
                            "| FOMC | 1d | raw_return | 65 |",
                            "| FOMC | 1d | zzz_return | 65 |", td)
            with self.assertRaises(ValueError):
                _build(i2b_path=bad)

    def test_34_repeated_copy_mismatch_refusal(self):
        # I2C-A repeats each MEMP; a divergent copy must refuse service.
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(SOURCES["i2c_calibration"],
                            "| FOMC | 1d | raw_return | 65 | 1816 | "
                            "0.674559 |",
                            "| FOMC | 1d | raw_return | 65 | 1816 | "
                            "0.674560 |", td)
            with self.assertRaises(ValueError):
                _build(i2c_calibration_path=bad)

    def test_35_malformed_falsifier_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            text = SOURCES["i2c_falsifiers"].read_text(encoding="utf-8")
            row = next(line for line in text.splitlines()
                       if line.startswith("| OPEC | 20d | sar |"))
            bad = Path(td) / SOURCES["i2c_falsifiers"].name
            bad.write_text(text.replace(row + "\n", ""), encoding="utf-8")
            with self.assertRaises(ValueError):
                _build(i2c_falsifiers_path=bad)

    def test_38_no_partial_payload_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            # NB: the frozen wording wraps across source lines; tamper the
            # single-line fragment.
            bad = _tampered(SOURCES["closeout"],
                            "formal hypothesis test", "GONE", td)
            try:
                out = _build(closeout_path=bad)
            except ValueError:
                out = None
            self.assertIsNone(out)


# ---------------------------------------------------------------------------
# API behavior (protections 36-37)
# ---------------------------------------------------------------------------


class EndpointTests(unittest.TestCase):
    def test_37_get_serves_builder_output(self):
        from fastapi.testclient import TestClient

        import api as api_mod

        with TestClient(api_mod.app) as client:
            resp = client.get("/evidence/mission-i")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body, json.loads(json.dumps(_payload())))
        self.assertEqual(len(body["primary_cells"]), 20)
        self.assertEqual(len(body["universe"]["families"]), 2)
        self.assertEqual(len(body["calibration"]["groups"]), 5)
        self.assertEqual(len(body["falsifiers"]["f4_cross_metric"]), 5)
        self.assertEqual(len(body["falsifiers"]["f5_cross_horizon"]), 8)

    def test_36_drift_returns_stable_sanitized_503(self):
        from fastapi.testclient import TestClient

        import api as api_mod

        def boom(**_k):
            raise ValueError(
                "mission-i artifact drift: C:\\private\\stats\\file.md "
                "regex <secret-pattern> failed")

        with patch.object(mie, "build_mission_i_evidence_summary", boom):
            with TestClient(api_mod.app) as client:
                resp = client.get("/evidence/mission-i")
        self.assertEqual(resp.status_code, 503)
        detail = resp.json()["detail"]
        self.assertEqual(
            detail,
            "mission-i research record unavailable (tracked artifact "
            "drift or unreadable source)")
        self.assertNotIn("private", resp.text)
        self.assertNotIn("secret-pattern", resp.text)
        self.assertNotIn("Traceback", resp.text)


if __name__ == "__main__":
    unittest.main()
