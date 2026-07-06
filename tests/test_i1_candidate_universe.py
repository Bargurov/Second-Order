"""Mission I1 — ordinary-period candidate-universe and funnel.

These tests protect ONLY the mechanical construction defined by the frozen
Mission I0 protocol (stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md, i0-v1):
did the code build exactly the ordinary-date reference universes, exclusion
sets, and denominator funnels frozen in I0?  No substantive event-vs-ordinary
comparison, no MEMP, no percentile ranks, no calibration, no outcome values.

Everything here is date / session-index / count geometry.  No arithmetic is
performed on price close values.  Reads are read-only against the gitignored
g3_price_cache.db substrate (same as the G3 grinder).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import db as _db
import event_study_validation as esv
from scripts import i1_candidate_universe as i1

ROOT = Path(__file__).resolve().parents[1]
G1B_DOC = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"


# One shared build of the real universe (deterministic; read-only cache).
_UNIVERSE = None


def universe():
    global _UNIVERSE
    if _UNIVERSE is None:
        _UNIVERSE = i1.build_universe()
    return _UNIVERSE


def lane(key):
    return universe()[key]


# ---------------------------------------------------------------------------
# Study denominators — the two pools stay separate and exact.
# ---------------------------------------------------------------------------


class StudyDenominatorTest(unittest.TestCase):
    def test_fomc_study_denominator_is_65(self):
        self.assertEqual(lane("FOMC").study_denominator, 65)
        self.assertEqual(len(lane("FOMC").study_event_dates), 65)

    def test_opec_study_denominator_is_32(self):
        self.assertEqual(lane("OPEC").study_denominator, 32)
        self.assertEqual(len(lane("OPEC").study_event_dates), 32)


# ---------------------------------------------------------------------------
# OPEC known-date exclusion register — 41 dates → 39 anchors, and it is a
# CONTAMINATION-control set only: never a study-denominator member.
# ---------------------------------------------------------------------------


class OpecRegisterTest(unittest.TestCase):
    def test_register_has_41_calendar_dates(self):
        reg = i1.build_opec_register()
        self.assertEqual(len(reg.dates), 41)
        self.assertEqual(len(set(reg.dates)), 41)

    def test_register_is_38_ledger_source_dates_plus_3_cited_extras(self):
        reg = i1.build_opec_register()
        self.assertEqual(len(reg.discovery_source_dates), 38)
        self.assertEqual(len(set(reg.discovery_source_dates)), 38)
        self.assertEqual(len(reg.extras), 3)
        # the 3 named extras are genuinely additional, not double-counts
        self.assertEqual(set(reg.extras) & set(reg.discovery_source_dates), set())
        self.assertEqual(
            set(reg.dates), set(reg.discovery_source_dates) | set(reg.extras)
        )

    def test_register_extras_are_exactly_the_three_named_dates(self):
        reg = i1.build_opec_register()
        self.assertEqual(
            set(reg.extras), {"2020-03-06", "2022-12-04", "2025-05-28"}
        )

    def test_register_extras_appear_in_tracked_g1b_doc(self):
        doc = G1B_DOC.read_text(encoding="utf-8")
        for extra in i1.OPEC_REGISTER_EXTRAS:
            self.assertIn(extra, doc, f"{extra} must be citable in G1B doc")

    def test_register_resolves_to_39_unique_anchor_sessions(self):
        self.assertEqual(len(lane("OPEC").exclusion_anchor_indices), 39)

    def test_register_dates_never_enter_the_32_event_study_denominator(self):
        opec = lane("OPEC")
        study = set(opec.study_event_dates)
        # the two named non-material meetings are exclusion-only by construction
        self.assertIn("2022-12-04", opec.exclusion_dates)
        self.assertIn("2025-05-28", opec.exclusion_dates)
        self.assertNotIn("2022-12-04", study)
        self.assertNotIn("2025-05-28", study)
        # denominator is exactly 32 regardless of the 41-date register
        self.assertEqual(opec.study_denominator, 32)
        self.assertEqual(len(opec.exclusion_dates), 41)


# ---------------------------------------------------------------------------
# FOMC exclusion set = its complete 65-frame (65 anchors).
# ---------------------------------------------------------------------------


class FomcExclusionTest(unittest.TestCase):
    def test_fomc_exclusion_is_the_65_frame(self):
        fomc = lane("FOMC")
        self.assertEqual(len(fomc.exclusion_dates), 65)
        self.assertEqual(sorted(fomc.exclusion_dates), sorted(fomc.study_event_dates))
        self.assertEqual(len(fomc.exclusion_anchor_indices), 65)


# ---------------------------------------------------------------------------
# Frozen candidate counts (blocker if mismatch) and per-horizon funnel.
# ---------------------------------------------------------------------------


class FrozenCandidateCountTest(unittest.TestCase):
    def test_fomc_counts_1816_1299_0(self):
        cells = lane("FOMC").cells
        self.assertEqual(cells[1].final_count, 1816)
        self.assertEqual(cells[5].final_count, 1299)
        self.assertEqual(cells[20].final_count, 0)

    def test_opec_counts_1903_1631_889(self):
        cells = lane("OPEC").cells
        self.assertEqual(cells[1].final_count, 1903)
        self.assertEqual(cells[5].final_count, 1631)
        self.assertEqual(cells[20].final_count, 889)

    def test_fomc_20d_status_is_structurally_infeasible(self):
        cell = lane("FOMC").cells[20]
        self.assertEqual(cell.status, "structurally_infeasible")
        self.assertFalse(cell.feasible)
        # structural, not a data gap: estimation/forward remove nothing;
        # the exclusion geometry annihilates the whole era.
        self.assertEqual(cell.estimation_casualties, 0)
        self.assertEqual(cell.forward_casualties, 0)
        self.assertEqual(cell.exclusion_casualties, cell.era_count)

    def test_all_other_cells_feasible(self):
        for key, hs in (("FOMC", (1, 5)), ("OPEC", (1, 5, 20))):
            for h in hs:
                cell = lane(key).cells[h]
                self.assertTrue(cell.feasible, f"{key} h={h}")
                self.assertEqual(cell.status, "feasible", f"{key} h={h}")


class FunnelGeometryTest(unittest.TestCase):
    def test_estimation_and_forward_remove_nothing_in_era(self):
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                cell = lane(key).cells[h]
                self.assertEqual(cell.estimation_casualties, 0, f"{key} est h={h}")
                self.assertEqual(cell.forward_casualties, 0, f"{key} fwd h={h}")

    def test_interior_gap_guard_fires_zero_times(self):
        # No >5-calendar-day interior gap exists between consecutive US
        # sessions in-era; the guard is faithful-but-moot at every cell.
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                self.assertEqual(lane(key).cells[h].gap_casualties, 0, f"{key} h={h}")

    def test_funnel_reconciles_input_minus_casualties_equals_survivors(self):
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                c = lane(key).cells[h]
                self.assertEqual(
                    c.era_count
                    - c.estimation_casualties
                    - c.forward_casualties
                    - c.gap_casualties
                    - c.exclusion_casualties,
                    c.final_count,
                    f"{key} h={h}",
                )

    def test_block_count_is_final_floor_div_h(self):
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                c = lane(key).cells[h]
                self.assertEqual(c.block_count, c.final_count // h, f"{key} h={h}")


# ---------------------------------------------------------------------------
# Frame pins — fail loud if the substrate drifted.
# ---------------------------------------------------------------------------


class FramePinTest(unittest.TestCase):
    def test_real_frames_are_2385_joint_and_2011_era(self):
        for key in ("FOMC", "OPEC"):
            self.assertEqual(len(lane(key).joint_sessions), 2385)
            self.assertEqual(len(lane(key).era_indices), 2011)

    def test_verify_pins_raises_on_joint_mismatch(self):
        with self.assertRaises(RuntimeError):
            i1.verify_pins(2384, 2011)

    def test_verify_pins_raises_on_era_mismatch(self):
        with self.assertRaises(RuntimeError):
            i1.verify_pins(2385, 2010)

    def test_zero_raw_only_sessions_both_lanes(self):
        # F3 faithfulness: adjusted coverage == raw coverage → basis uniformly
        # adjusted, no cross-basis; every joint session is adjusted-available.
        for key in ("FOMC", "OPEC"):
            self.assertEqual(lane(key).raw_only_sessions, 0)


# ---------------------------------------------------------------------------
# Gate equivalence — the per-horizon funnel reuses the SHIPPED gate's
# contract, it does not reimplement a second methodology.
# ---------------------------------------------------------------------------


class GateEquivalenceTest(unittest.TestCase):
    def _gate_available(self, frame_spec, iso):
        event = {"event_date": iso,
                 "market_tickers": [{"symbol": frame_spec.primary}]}
        vs_bench = esv.build_event_study_validation(
            event, benchmark_ticker=frame_spec.benchmark)
        vs_sector = esv.build_event_study_validation(
            event, benchmark_ticker=frame_spec.sector)
        return (vs_bench.get("status") == esv.STATUS_AVAILABLE
                and vs_sector.get("status") == esv.STATUS_AVAILABLE)

    def test_preexclusion_h20_equals_shipped_gate_and(self):
        saved = _db.DB_FILE
        _db.DB_FILE = str(i1.default_db_path())
        try:
            for spec in (i1.FOMC_SPEC, i1.OPEC_SPEC):
                frame = i1.adjusted_joint_frame(spec)
                n = len(frame)
                # spread of interior samples plus the est/forward boundaries
                sample = list(range(0, n, 97)) + [59, 60, 61, n - 21, n - 20, n - 1]
                for idx in sorted(set(i for i in sample if 0 <= i < n)):
                    iso = frame[idx]
                    mine = i1.is_preexclusion_eligible(frame, idx, 20)
                    self.assertEqual(
                        mine, self._gate_available(spec, iso),
                        f"{spec.key} idx={idx} {iso}")
        finally:
            _db.DB_FILE = saved


# ---------------------------------------------------------------------------
# Per-year coverage — OPEC keeps all eight years at every feasible horizon.
# ---------------------------------------------------------------------------


class PerYearCoverageTest(unittest.TestCase):
    def test_opec_retains_all_eight_years_every_horizon(self):
        for h in (1, 5, 20):
            per_year = lane("OPEC").cells[h].per_year
            years = {str(y) for y in range(2018, 2026)}
            self.assertEqual(set(per_year), years, f"h={h}")
            for y in years:
                self.assertGreater(per_year[y], 0, f"h={h} year={y}")


# ---------------------------------------------------------------------------
# Determinism + outcome-blindness firewall.
# ---------------------------------------------------------------------------


class DeterminismTest(unittest.TestCase):
    def test_rebuild_and_report_are_byte_identical(self):
        a = i1.build_universe()
        b = i1.build_universe()
        self.assertEqual(i1.render_report(a), i1.render_report(b))

    def test_report_is_deterministic_string(self):
        self.assertIsInstance(i1.render_report(universe()), str)

    def test_tracked_report_matches_builder_output(self):
        # The shipped artifact must regenerate byte-identically from the
        # builder (timestamp-free) — no silent drift between code and report.
        tracked = (ROOT / "stats" / "I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md")
        self.assertEqual(
            tracked.read_text(encoding="utf-8"),
            i1.render_report(universe()),
            "tracked I1 report is stale — regenerate it from the builder")


class OutcomeBlindnessTest(unittest.TestCase):
    def test_module_does_not_reference_the_return_engine(self):
        src = (ROOT / "scripts" / "i1_candidate_universe.py").read_text(
            encoding="utf-8")
        self.assertNotIn("compute_event_study", src)

    def test_report_carries_no_outcome_value_vocabulary(self):
        report = i1.render_report(universe())
        banned = ["abnormal return", "percentile", "p-value", "p value",
                  "memp", "calibration", "sigma", "correlation", "significan"]
        for line in report.splitlines():
            low = line.lower()
            negated = ("not " in low or "no " in low or "never" in low
                       or "does not" in low)
            for token in banned:
                if token in low and not negated:
                    self.fail(f"outcome vocabulary {token!r} in: {line}")


if __name__ == "__main__":
    unittest.main()
