"""Mission I1 — ordinary-period candidate-universe and funnel.

These tests protect ONLY the mechanical construction defined by the frozen
Mission I0 protocol (stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md, i0-v1):
did the code build exactly the ordinary-date reference universes, exclusion
sets, and denominator funnels frozen in I0?  No substantive event-vs-ordinary
comparison, no MEMP, no percentile ranks, no calibration, no outcome values.

T2 substrate contract — three input layers, kept distinct:

* **logic** (``CATEGORY_LOGIC``) — pure date / session-index / count
  mechanics proven on minimal deterministic fixtures; default-run.
* **publication** (``CATEGORY_PUBLICATION``) — durable contracts read from
  tracked artifacts (the G1A/G1B ledgers and the tracked I1 report);
  default-run.  A fixture never impersonates the historical universe;
  the frozen numbers are asserted against the committed publication.
* **local recomputation** (``CATEGORY_LOCAL_RECOMPUTATION``) — rebuilding
  the real 2,385-session universe from the maintainer's gitignored
  ``g3_price_cache.db``.  Explicit opt-in only::

      SECOND_ORDER_RUN_LOCAL_DATA_TESTS=1
      SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE=<path to g3_price_cache.db>

  File presence alone never activates these; the builder's fail-loud
  session pins refuse any substrate that is not the pinned frame.

Reads are read-only; nothing here writes a database or calls a provider.
"""
from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

import db as _db
import event_study_validation as esv
from scripts import i1_candidate_universe as i1

# T2: Mission I local recomputation is explicit opt-in via the shared gate;
# substrate presence must not change the default universe.
from tests._local_data_gate import (  # noqa: E402
    local_mission_i_substrate_or_none,
    mission_i_skip_reason,
)

ROOT = Path(__file__).resolve().parents[1]
G1B_DOC = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"
I1_REPORT = ROOT / "stats" / "I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md"

_SUBSTRATE = local_mission_i_substrate_or_none()
_local_recomputation = unittest.skipUnless(
    _SUBSTRATE is not None, mission_i_skip_reason()
)


# One shared build of the real universe (deterministic; read-only cache).
# Only local-recomputation tests may call this; the gate guarantees the
# explicit substrate path is present before any of them run.
_UNIVERSE = None


def universe():
    global _UNIVERSE
    if _UNIVERSE is None:
        _UNIVERSE = i1.build_universe(db_path=_SUBSTRATE)
    return _UNIVERSE


def lane(key):
    return universe()[key]


def _tracked_report_text() -> str:
    return I1_REPORT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T2 category map — pinned by tests/test_mission_i_substrate_contract.py.
# Every test in this module appears in exactly one tuple.
# ---------------------------------------------------------------------------

CATEGORY_LOGIC = (
    "FramePinTest.test_verify_pins_raises_on_joint_mismatch",
    "FramePinTest.test_verify_pins_raises_on_era_mismatch",
    "NonOverlapBlockCountTest.test_contiguous_run_closed_form",
    "NonOverlapBlockCountTest.test_exclusion_holes_are_handled",
    "NonOverlapWindowLogicTest.test_selected_windows_share_no_session_on_fixture",
    "NonOverlapWindowLogicTest.test_greedy_is_maximal_on_fixture",
    "NonOverlapWindowLogicTest.test_block_count_never_exceeds_eligible_on_fixture",
    "FunnelSieveLogicTest.test_funnel_reconciles_on_fixture_frame",
    "FunnelSieveLogicTest.test_exclusion_buffer_drops_within_h_of_anchor",
    "FunnelSieveLogicTest.test_infeasible_status_when_exclusions_annihilate",
    "FunnelSieveLogicTest.test_block_count_equals_canonical_subset_on_fixture",
    "AnchorResolutionLogicTest.test_session_index_is_last_on_or_before",
    "AnchorResolutionLogicTest.test_exclusion_date_before_frame_raises",
    "OutcomeBlindnessTest.test_module_does_not_reference_the_return_engine",
)

CATEGORY_PUBLICATION = (
    "StudyDenominatorTest.test_fomc_study_denominator_is_65",
    "StudyDenominatorTest.test_opec_study_denominator_is_32",
    "OpecRegisterTest.test_register_has_41_calendar_dates",
    "OpecRegisterTest.test_register_is_38_ledger_source_dates_plus_3_cited_extras",
    "OpecRegisterTest.test_register_extras_are_exactly_the_three_named_dates",
    "OpecRegisterTest.test_register_extras_appear_in_tracked_g1b_doc",
    "OpecRegisterTest.test_register_dates_never_enter_the_32_event_study_denominator",
    "FrozenCountsPublicationTest.test_tracked_report_pins_fomc_funnel_rows",
    "FrozenCountsPublicationTest.test_tracked_report_pins_opec_funnel_rows",
    "FrozenCountsPublicationTest.test_tracked_report_pins_frame_and_register_geometry",
    "OutcomeBlindnessTest.test_report_carries_no_outcome_value_vocabulary",
    "CliEmitPortabilityTest.test_report_has_a_char_a_legacy_console_cannot_encode",
    "CliEmitPortabilityTest.test_emit_report_writes_utf8_through_cp1252_stdout",
    "CliEmitPortabilityTest.test_emit_report_preserves_render_report_bytes",
    "CliEmitPortabilityTest.test_emit_report_falls_back_to_text_write",
)

CATEGORY_LOCAL_RECOMPUTATION = (
    "LiveLaneWiringTest.test_lane_study_denominators_are_65_and_32",
    "FomcExclusionTest.test_fomc_exclusion_is_the_65_frame",
    "OpecRegisterTest.test_register_resolves_to_39_unique_anchor_sessions",
    "FrozenCandidateCountTest.test_fomc_counts_1816_1299_0",
    "FrozenCandidateCountTest.test_opec_counts_1903_1631_889",
    "FrozenCandidateCountTest.test_fomc_20d_status_is_structurally_infeasible",
    "FrozenCandidateCountTest.test_all_other_cells_feasible",
    "FunnelGeometryTest.test_estimation_and_forward_remove_nothing_in_era",
    "FunnelGeometryTest.test_interior_gap_guard_fires_zero_times",
    "FunnelGeometryTest.test_funnel_reconciles_input_minus_casualties_equals_survivors",
    "NonOverlapBlockCountTest.test_block_count_equals_canonical_subset_size",
    "NonOverlapBlockCountTest.test_selected_windows_share_no_session",
    "NonOverlapBlockCountTest.test_block_count_never_exceeds_eligible",
    "NonOverlapBlockCountTest.test_greedy_selection_is_maximal",
    "FramePinTest.test_real_frames_are_2385_joint_and_2011_era",
    "FramePinTest.test_zero_raw_only_sessions_both_lanes",
    "GateEquivalenceTest.test_preexclusion_h20_equals_shipped_gate_and",
    "PerYearCoverageTest.test_opec_retains_all_eight_years_every_horizon",
    "DeterminismTest.test_rebuild_and_report_are_byte_identical",
    "DeterminismTest.test_report_is_deterministic_string",
    "DeterminismTest.test_tracked_report_matches_builder_output",
)


# ---------------------------------------------------------------------------
# Study denominators — durable ledger contracts (tracked G1A / G1B).
# The two pools stay separate and exact.
# ---------------------------------------------------------------------------


class StudyDenominatorTest(unittest.TestCase):
    def test_fomc_study_denominator_is_65(self):
        dates = i1.parse_fomc_frame_dates()
        self.assertEqual(len(dates), 65)
        self.assertEqual(len(set(dates)), 65)

    def test_opec_study_denominator_is_32(self):
        dates = i1.parse_opec_study_dates()
        self.assertEqual(len(dates), 32)
        self.assertEqual(len(set(dates)), 32)


# ---------------------------------------------------------------------------
# OPEC known-date exclusion register — 41 dates, and it is a
# CONTAMINATION-control set only: never a study-denominator member.
# Ledger-level facts are tracked-publication contracts; the 41→39 anchor
# resolution needs the real session frame (local recomputation).
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

    @_local_recomputation
    def test_register_resolves_to_39_unique_anchor_sessions(self):
        self.assertEqual(len(lane("OPEC").exclusion_anchor_indices), 39)

    def test_register_dates_never_enter_the_32_event_study_denominator(self):
        study = set(i1.parse_opec_study_dates())
        reg = i1.build_opec_register()
        # the two named non-material meetings are exclusion-only by construction
        self.assertIn("2022-12-04", reg.dates)
        self.assertIn("2025-05-28", reg.dates)
        self.assertNotIn("2022-12-04", study)
        self.assertNotIn("2025-05-28", study)
        # denominator is exactly 32 regardless of the 41-date register
        self.assertEqual(len(study), 32)
        self.assertEqual(len(reg.dates), 41)


# ---------------------------------------------------------------------------
# FOMC exclusion set = its complete 65-frame (65 anchors) — verifying the
# builder's wiring against the real frame is local recomputation.
# ---------------------------------------------------------------------------


class FomcExclusionTest(unittest.TestCase):
    @_local_recomputation
    def test_fomc_exclusion_is_the_65_frame(self):
        fomc = lane("FOMC")
        self.assertEqual(len(fomc.exclusion_dates), 65)
        self.assertEqual(sorted(fomc.exclusion_dates), sorted(fomc.study_event_dates))
        self.assertEqual(len(fomc.exclusion_anchor_indices), 65)


class LiveLaneWiringTest(unittest.TestCase):
    @_local_recomputation
    def test_lane_study_denominators_are_65_and_32(self):
        self.assertEqual(lane("FOMC").study_denominator, 65)
        self.assertEqual(len(lane("FOMC").study_event_dates), 65)
        self.assertEqual(lane("OPEC").study_denominator, 32)
        self.assertEqual(len(lane("OPEC").study_event_dates), 32)


# ---------------------------------------------------------------------------
# Frozen candidate counts — recomputing them requires the real substrate;
# the frozen numbers themselves are pinned as tracked-publication contracts
# in FrozenCountsPublicationTest below.
# ---------------------------------------------------------------------------


@_local_recomputation
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


class FrozenCountsPublicationTest(unittest.TestCase):
    """The frozen Mission I numbers as durable tracked-publication pins.

    These read the committed I1 report — never a recomputation, never a
    fixture.  The report↔builder byte-reconciliation (which does require
    the substrate) lives in DeterminismTest under the explicit opt-in.
    """

    def test_tracked_report_pins_fomc_funnel_rows(self):
        text = _tracked_report_text()
        fomc = text.split("## OPEC lane")[0]
        self.assertIn("**1816**", fomc)
        self.assertIn("**1299**", fomc)
        self.assertRegex(
            fomc, r"\| 20d \| 2011 \| 0 \| 0 \| 0 \| 2011 \| \*\*0\*\* \| 0 "
                  r"\| structurally_infeasible \|")

    def test_tracked_report_pins_opec_funnel_rows(self):
        text = _tracked_report_text()
        opec = text.split("## OPEC lane")[1]
        self.assertIn("**1903**", opec)
        self.assertIn("**1631**", opec)
        self.assertIn("**889**", opec)

    def test_tracked_report_pins_frame_and_register_geometry(self):
        text = _tracked_report_text()
        self.assertEqual(text.count(
            "Joint (triple-intersection) sessions: **2385**"), 2)
        self.assertIn("era 2018–2025 sessions: **2011**", text)
        self.assertIn("**41** calendar dates", text)
        self.assertIn("**39** anchor", text)
        self.assertIn(
            "Exclusion set: the complete 65-event frame → **65** anchor",
            text)


@_local_recomputation
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


# ---------------------------------------------------------------------------
# Funnel sieve mechanics on a minimal deterministic fixture frame (logic).
# ---------------------------------------------------------------------------


def _weekday_frame(start_iso: str, n: int) -> list[str]:
    """n consecutive weekday ISO dates — a contiguous synthetic frame."""
    from datetime import date, timedelta

    d = date.fromisoformat(start_iso)
    out: list[str] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class FunnelSieveLogicTest(unittest.TestCase):
    """I0 §17 sieve mechanics proven on a small fixture.

    The fixture is a test-input contract for the sieve arithmetic only —
    it asserts nothing about the historical 2,385-session universe.
    """

    def _fixture(self, anchors_iso=(), h=5):
        # 200 weekdays straddling the era boundary: enough room for the
        # 60-session estimation window inside the era.
        frame = _weekday_frame("2017-11-01", 200)
        era = i1.era_indices(frame)
        anchors = i1.resolve_anchor_indices(frame, anchors_iso) if anchors_iso else []
        cell = i1.build_funnel_cell(i1.FOMC_SPEC, frame, era, anchors, h)
        return frame, era, anchors, cell

    def test_funnel_reconciles_on_fixture_frame(self):
        for h in (1, 5, 20):
            _, era, _, cell = self._fixture(("2018-06-01",), h=h)
            self.assertEqual(
                cell.era_count
                - cell.estimation_casualties
                - cell.forward_casualties
                - cell.gap_casualties
                - cell.exclusion_casualties,
                cell.final_count,
                f"h={h}",
            )
            self.assertEqual(cell.era_count, len(era))

    def test_exclusion_buffer_drops_within_h_of_anchor(self):
        h = 5
        frame, _, anchors, cell = self._fixture(("2018-06-01",), h=h)
        self.assertEqual(len(anchors), 1)
        anchor = anchors[0]
        buffered = {i for i in cell.candidate_indices
                    if abs(i - anchor) <= h}
        self.assertEqual(buffered, set(),
                         "no surviving candidate may sit within h of an anchor")

    def test_infeasible_status_when_exclusions_annihilate(self):
        # Anchors spaced so every era session is within h of one of them.
        h = 20
        frame = _weekday_frame("2017-11-01", 200)
        era = i1.era_indices(frame)
        anchor_dates = [frame[i] for i in era[:: h]]
        anchors = i1.resolve_anchor_indices(frame, anchor_dates)
        cell = i1.build_funnel_cell(i1.FOMC_SPEC, frame, era, anchors, h)
        self.assertEqual(cell.final_count, 0)
        self.assertFalse(cell.feasible)
        self.assertEqual(cell.status, "structurally_infeasible")

    def test_block_count_equals_canonical_subset_on_fixture(self):
        for h in (1, 5):
            _, _, _, cell = self._fixture(("2018-06-01",), h=h)
            picks = i1.canonical_non_overlapping_windows(
                cell.candidate_indices, h)
            self.assertEqual(cell.block_count, len(picks), f"h={h}")


class AnchorResolutionLogicTest(unittest.TestCase):
    def test_session_index_is_last_on_or_before(self):
        frame = ["2024-03-05", "2024-03-06", "2024-03-07"]
        self.assertEqual(i1.session_index(frame, "2024-03-06"), 1)
        # A non-session date resolves to the last session on-or-before it.
        self.assertEqual(i1.session_index(frame, "2024-03-09"), 2)

    def test_exclusion_date_before_frame_raises(self):
        frame = ["2024-03-05", "2024-03-06", "2024-03-07"]
        with self.assertRaisesRegex(RuntimeError, "precedes the joint frame"):
            i1.resolve_anchor_indices(frame, ["2024-03-01"])


class NonOverlapBlockCountTest(unittest.TestCase):
    """The block count must be an actual count of disjoint response windows.

    Under the frozen I0 sec.8 semantics a response window is [t, t+h] and two
    windows 'share no session' iff their starts are separated by >= h+1 (a
    shared endpoint at distance exactly h IS overlap, matching the exclusion
    buffer that drops |i-e| <= h). The block count is the size of the
    canonical greedy earliest-first maximal set of such windows on the
    eligible session indices -- NOT eligible_count // h, which ignores index
    positions (exclusion holes) and the window span.
    """

    @_local_recomputation
    def test_block_count_equals_canonical_subset_size(self):
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                c = lane(key).cells[h]
                picks = i1.canonical_non_overlapping_windows(
                    c.candidate_indices, h)
                self.assertEqual(c.block_count, len(picks), f"{key} h={h}")

    @_local_recomputation
    def test_selected_windows_share_no_session(self):
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                picks = i1.canonical_non_overlapping_windows(
                    lane(key).cells[h].candidate_indices, h)
                for a, b in zip(picks, picks[1:]):
                    self.assertGreaterEqual(b - a, h + 1, f"{key} h={h}")

    @_local_recomputation
    def test_block_count_never_exceeds_eligible(self):
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                c = lane(key).cells[h]
                self.assertLessEqual(c.block_count, c.final_count, f"{key} h={h}")

    @_local_recomputation
    def test_greedy_selection_is_maximal(self):
        # No non-selected eligible start could be added while preserving the
        # >= h+1 separation: every one lies within h of some pick.
        for key in ("FOMC", "OPEC"):
            for h in (1, 5, 20):
                idx = sorted(lane(key).cells[h].candidate_indices)
                picks = i1.canonical_non_overlapping_windows(idx, h)
                pickset = set(picks)
                for i in idx:
                    if i in pickset:
                        continue
                    self.assertTrue(
                        any(abs(i - p) <= h for p in picks),
                        f"{key} h={h} idx={i} is addable -> not maximal")

    def test_contiguous_run_closed_form(self):
        # A hole-free run 0..N-1 packs at starts 0, h+1, 2(h+1), ...
        for n, h in ((10, 1), (100, 5), (41, 20), (1, 1), (2, 1), (21, 20)):
            picks = i1.canonical_non_overlapping_windows(list(range(n)), h)
            self.assertEqual(len(picks), (n - 1) // (h + 1) + 1, f"n={n} h={h}")
            self.assertEqual(picks[0], 0)

    def test_exclusion_holes_are_handled(self):
        # Two dense clusters far apart: greedy packs inside each; the hole
        # neither creates nor destroys a window. eligible_count // h would
        # miss this entirely.
        idx = [0, 1, 2, 100, 101, 102]
        self.assertEqual(
            i1.canonical_non_overlapping_windows(idx, 1), [0, 2, 100, 102])
        self.assertEqual(
            i1.canonical_non_overlapping_windows(idx, 5), [0, 100])


class NonOverlapWindowLogicTest(unittest.TestCase):
    """The live-universe window properties, proven on fixture index sets."""

    _IDX = (0, 1, 2, 3, 7, 8, 9, 15, 30, 31)

    def test_selected_windows_share_no_session_on_fixture(self):
        for h in (1, 5, 20):
            picks = i1.canonical_non_overlapping_windows(list(self._IDX), h)
            for a, b in zip(picks, picks[1:]):
                self.assertGreaterEqual(b - a, h + 1, f"h={h}")

    def test_greedy_is_maximal_on_fixture(self):
        for h in (1, 5, 20):
            picks = i1.canonical_non_overlapping_windows(list(self._IDX), h)
            pickset = set(picks)
            for i in self._IDX:
                if i in pickset:
                    continue
                self.assertTrue(
                    any(abs(i - p) <= h for p in picks),
                    f"h={h} idx={i} is addable -> not maximal")

    def test_block_count_never_exceeds_eligible_on_fixture(self):
        for h in (1, 5, 20):
            picks = i1.canonical_non_overlapping_windows(list(self._IDX), h)
            self.assertLessEqual(len(picks), len(self._IDX))


# ---------------------------------------------------------------------------
# Frame pins — the raise-paths are pure logic; the real-substrate frame
# counts are local recomputation.
# ---------------------------------------------------------------------------


class FramePinTest(unittest.TestCase):
    @_local_recomputation
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

    @_local_recomputation
    def test_zero_raw_only_sessions_both_lanes(self):
        # F3 faithfulness: adjusted coverage == raw coverage → basis uniformly
        # adjusted, no cross-basis; every joint session is adjusted-available.
        for key in ("FOMC", "OPEC"):
            self.assertEqual(lane(key).raw_only_sessions, 0)


# ---------------------------------------------------------------------------
# Gate equivalence — the per-horizon funnel reuses the SHIPPED gate's
# contract, it does not reimplement a second methodology.  Requires the
# real substrate (previously passed VACUOUSLY on a clean clone because the
# empty frame produced zero samples — now honestly opt-in).
# ---------------------------------------------------------------------------


@_local_recomputation
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
        _db.DB_FILE = str(_SUBSTRATE)
        try:
            for spec in (i1.FOMC_SPEC, i1.OPEC_SPEC):
                frame = i1.adjusted_joint_frame(spec, _SUBSTRATE)
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


@_local_recomputation
class PerYearCoverageTest(unittest.TestCase):
    def test_opec_retains_all_eight_years_every_horizon(self):
        for h in (1, 5, 20):
            per_year = lane("OPEC").cells[h].per_year
            years = {str(y) for y in range(2018, 2026)}
            self.assertEqual(set(per_year), years, f"h={h}")
            for y in years:
                self.assertGreater(per_year[y], 0, f"h={h} year={y}")


# ---------------------------------------------------------------------------
# Determinism + code↔publication reconciliation (real substrate required).
# ---------------------------------------------------------------------------


@_local_recomputation
class DeterminismTest(unittest.TestCase):
    def test_rebuild_and_report_are_byte_identical(self):
        a = i1.build_universe(db_path=_SUBSTRATE)
        b = i1.build_universe(db_path=_SUBSTRATE)
        self.assertEqual(i1.render_report(a), i1.render_report(b))

    def test_report_is_deterministic_string(self):
        self.assertIsInstance(i1.render_report(universe()), str)

    def test_tracked_report_matches_builder_output(self):
        # The shipped artifact must regenerate byte-identically from the
        # builder (timestamp-free) — no silent drift between code and report.
        self.assertEqual(
            _tracked_report_text(),
            i1.render_report(universe()),
            "tracked I1 report is stale — regenerate it from the builder")


class OutcomeBlindnessTest(unittest.TestCase):
    def test_module_does_not_reference_the_return_engine(self):
        src = (ROOT / "scripts" / "i1_candidate_universe.py").read_text(
            encoding="utf-8")
        self.assertNotIn("compute_event_study", src)

    def test_report_carries_no_outcome_value_vocabulary(self):
        # Publication contract: the TRACKED report (byte-reconciled to the
        # builder under the opt-in DeterminismTest) carries no outcome
        # vocabulary.
        report = _tracked_report_text()
        banned = ["abnormal return", "percentile", "p-value", "p value",
                  "memp", "calibration", "sigma", "correlation", "significan"]
        for line in report.splitlines():
            low = line.lower()
            negated = ("not " in low or "no " in low or "never" in low
                       or "does not" in low)
            for token in banned:
                if token in low and not negated:
                    self.fail(f"outcome vocabulary {token!r} in: {line}")


# ---------------------------------------------------------------------------
# CLI emit portability — the report must reach stdout on a Windows console
# whose text layer uses a legacy code page (cp1252), without UnicodeEncodeError.
# The emit boundary is exercised against the TRACKED report text (the same
# bytes the builder emits when the substrate is present).
# ---------------------------------------------------------------------------


class CliEmitPortabilityTest(unittest.TestCase):
    @staticmethod
    def _cp1252_stdout():
        # A text stdout backed by a legacy Windows code page, exposing the
        # binary .buffer that a UTF-8 emit boundary should target -- the same
        # shape as the operator's real console stdout.
        raw = io.BytesIO()
        return io.TextIOWrapper(raw, encoding="cp1252", newline=""), raw

    def test_report_has_a_char_a_legacy_console_cannot_encode(self):
        # Premise of the whole task: the deterministic report really carries a
        # character (U+2192 '->') that cp1252 cannot encode, so a naive text
        # write reproduces the operator's UnicodeEncodeError exactly.
        report = _tracked_report_text()
        self.assertIn("→", report)
        wrapper, _ = self._cp1252_stdout()
        with self.assertRaises(UnicodeEncodeError):
            wrapper.write(report)
            wrapper.flush()

    def test_emit_report_writes_utf8_through_cp1252_stdout(self):
        report = _tracked_report_text()
        wrapper, raw = self._cp1252_stdout()
        i1.emit_report(report, stream=wrapper)  # must NOT raise
        self.assertEqual(raw.getvalue().decode("utf-8"), report)

    def test_emit_report_preserves_render_report_bytes(self):
        report = _tracked_report_text()
        wrapper, raw = self._cp1252_stdout()
        i1.emit_report(report, stream=wrapper)
        self.assertEqual(raw.getvalue(), report.encode("utf-8"))

    def test_emit_report_falls_back_to_text_write(self):
        # A stream with no binary .buffer (e.g. an in-memory text capture)
        # still receives the exact report.
        report = _tracked_report_text()
        sink = io.StringIO()
        i1.emit_report(report, stream=sink)
        self.assertEqual(sink.getvalue(), report)


if __name__ == "__main__":
    unittest.main()
