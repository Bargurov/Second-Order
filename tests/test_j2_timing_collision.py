"""J2 timing-and-collision tests (Mission J, j0-v1 contracts).

Everything here runs on deterministic SYNTHETIC fixtures only. No canonical
frozen input is opened, no provider or network function is reachable, and no
real Mission J timing or collision outcome value exists anywhere in this
suite. Synthetic results are engine-verification metadata, never research
evidence.

Protected contracts (task manifest):
  manifest 1-4; window geometry 5-10; state-bearing path 11-17;
  diagnostic-only path 18-22; collision geometry 23-31; reporting 32-37.
"""

from __future__ import annotations

import json
import math
import statistics
import unittest

import numpy as np

from scripts import i1_candidate_universe as i1
from scripts import j1b_outcome_engine as eng
from scripts import j2_timing_collision as j2
from tests.test_j1b_outcome_engine import (bdays, build_fixture,
                                           synth_closes, synthetic_auth)


# ---------------------------------------------------------------------------
# Deterministic synthetic fixtures (timing-specific)
# ---------------------------------------------------------------------------


def _event_anchor_indices(calendar: list[str],
                          events: list[str]) -> list[int]:
    out = []
    for d in events:
        idx = eng.last_index_le(calendar, d)
        assert idx is not None
        out.append(idx)
    return out


def build_timing_fixture(*, pre_event_shock: float = 0.0
                         ) -> "eng.EngineInputs":
    """KRE/SPY/XLF-only inputs; optional PRE-anchor KRE shocks.

    ``synth_closes`` shocks the return INTO session i when (i-1) is in
    ``event_idx``; passing {e-5..e-2} shocks the four returns into
    sessions e-4..e-1 - all inside the frozen [-5, -1] window and none
    inside [t, t+1].
    """
    calendar = bdays("2017-03-01", 2470)
    events = [f"{y}-{m}-15" for y in range(2018, 2026) for m in ("03", "09")]
    spy = synth_closes(calendar, 99, vol=0.009)
    bench_list = [spy[d] for d in calendar]
    shock_idx: set[int] = set()
    if pre_event_shock:
        for e in _event_anchor_indices(calendar, events):
            shock_idx.update(range(e - 5, e - 1))

    def both(m):
        return {"adjusted": dict(m), "raw": dict(m)}

    closes = {
        "SPY": both(spy),
        "KRE": both(synth_closes(calendar, 1, vol=0.012, beta=1.2,
                                 bench=bench_list, event_idx=shock_idx,
                                 event_shock=pre_event_shock)),
        "XLF": both(synth_closes(calendar, 4, vol=0.011, beta=1.0,
                                 bench=bench_list)),
    }
    return eng.EngineInputs(
        closes=closes,
        treasury={"two_yr": {}, "spread_2s10s": {}},
        event_dates=events,
        synthetic=True)


_CACHE: dict = {}


def preshock_result():
    if "pre" not in _CACHE:
        _CACHE["pre"] = j2.run_state_bearing(
            build_timing_fixture(pre_event_shock=0.08), synthetic_auth())
    return _CACHE["pre"]


def quiet_result():
    if "quiet" not in _CACHE:
        _CACHE["quiet"] = j2.run_state_bearing(
            build_timing_fixture(), synthetic_auth())
    return _CACHE["quiet"]


def quiet_diagnostics():
    if "diag" not in _CACHE:
        _CACHE["diag"] = j2.run_diagnostics(
            build_timing_fixture(), synthetic_auth())
    return _CACHE["diag"]


def raw_group_substrates():
    """J1B raw-ETF-group substrates on the shared J1B fixture (fast)."""
    if "subs" not in _CACHE:
        inputs = build_fixture()
        cells = [c for c in eng.FROZEN_CELLS
                 if c["cell"] in (6, 7, 8, 9, 12)]
        _CACHE["subs"] = [eng.build_cell_substrate(c, inputs)
                          for c in cells]
        _CACHE["subs_events"] = list(inputs.event_dates)
    return _CACHE["subs"], _CACHE["subs_events"]


# ---------------------------------------------------------------------------
# Manifest (protections 1-4)
# ---------------------------------------------------------------------------


class TestManifest(unittest.TestCase):
    def test_1_exactly_four_state_bearing_cells(self):
        got = [(c["cell"], c["measurement"], c["metric"], tuple(c["window"]))
               for c in j2.TIMING_CELLS]
        self.assertEqual(got, [
            (13, "KRE", "raw_return", (-5, -1)),
            (14, "KRE", "spy_relative_ar", (-5, -1)),
            (15, "KRE", "sector_relative_ar", (-5, -1)),
            (16, "KRE", "sar", (-5, -1)),
        ])

    def test_2_exactly_four_diagnostics(self):
        got = [(d["diagnostic"], d["metric"], tuple(d["window"]))
               for d in j2.TIMING_DIAGNOSTICS]
        self.assertEqual(got, [
            ("D1", "raw_return", (-20, -1)),
            ("D2", "spy_relative_ar", (-20, -1)),
            ("D3", "sector_relative_ar", (-20, -1)),
            ("D4", "sar", (-20, -1)),
        ])

    def test_3_no_ninth_timing_statistic(self):
        self.assertEqual(len(j2.TIMING_CELLS), 4)
        self.assertEqual(len(j2.TIMING_DIAGNOSTICS), 4)
        self.assertEqual(j2.STATE_BEARING_WINDOW, (-5, -1))
        self.assertEqual(j2.DIAGNOSTIC_WINDOW, (-20, -1))
        # No alternative timing window exists anywhere in the module.
        import inspect
        src = inspect.getsource(j2)
        for banned in ("(-1, 0)", "(-3, -1)", "(-10, -1)"):
            self.assertNotIn(banned, src)

    def test_4_frozen_order_and_results_preserve_it(self):
        res = quiet_result()
        self.assertEqual([c["cell"] for c in res["cells"]],
                         [13, 14, 15, 16])
        self.assertEqual([c["metric"] for c in res["cells"]],
                         list(j2.METRICS))
        diag = quiet_diagnostics()
        self.assertEqual([d["diagnostic"] for d in diag["diagnostics"]],
                         ["D1", "D2", "D3", "D4"])

    def test_4b_inherited_metric_order_is_the_i2a_order(self):
        self.assertEqual(j2.METRICS, ("raw_return", "spy_relative_ar",
                                      "sector_relative_ar", "sar"))


# ---------------------------------------------------------------------------
# Window geometry (protections 5-10)
# ---------------------------------------------------------------------------


class TestWindowGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = build_timing_fixture()
        cls.frame, cls.basis, cls.fallback = j2.triple_joint_frame(
            cls.inputs.closes)
        cls.kre = cls.inputs.closes["KRE"]["adjusted"]
        cls.spy = cls.inputs.closes["SPY"]["adjusted"]
        cls.xlf = cls.inputs.closes["XLF"]["adjusted"]

    def _respond(self, idx, window):
        return j2.timing_response(self.kre, self.spy, self.xlf,
                                  self.frame, idx, window)

    def test_5_exact_minus5_minus1_session_membership(self):
        idx = 400
        values, reason = self._respond(idx, (-5, -1))
        self.assertIsNone(reason)
        f = self.frame
        raw = self.kre[f[idx - 1]] / self.kre[f[idx - 5]] - 1.0
        spy_r = self.spy[f[idx - 1]] / self.spy[f[idx - 5]] - 1.0
        xlf_r = self.xlf[f[idx - 1]] / self.xlf[f[idx - 5]] - 1.0
        self.assertAlmostEqual(values["raw_return"], raw, places=15)
        self.assertAlmostEqual(values["spy_relative_ar"], raw - spy_r,
                               places=15)
        self.assertAlmostEqual(values["sector_relative_ar"], raw - xlf_r,
                               places=15)
        # SAR: sigma from the 60 daily ARs ending at the window start.
        est = f[idx - 65: idx - 4]
        ka = np.array([self.kre[d] for d in est])
        sa = np.array([self.spy[d] for d in est])
        dar = (ka[1:] / ka[:-1] - 1.0) - (sa[1:] / sa[:-1] - 1.0)
        sigma = float(np.std(dar, ddof=1))
        self.assertAlmostEqual(values["sar"],
                               (raw - spy_r) / (sigma * math.sqrt(4)),
                               places=12)

    def test_6_exact_minus20_minus1_session_membership(self):
        idx = 400
        values, reason = self._respond(idx, (-20, -1))
        self.assertIsNone(reason)
        f = self.frame
        raw = self.kre[f[idx - 1]] / self.kre[f[idx - 20]] - 1.0
        spy_r = self.spy[f[idx - 1]] / self.spy[f[idx - 20]] - 1.0
        self.assertAlmostEqual(values["raw_return"], raw, places=15)
        est = f[idx - 80: idx - 19]
        ka = np.array([self.kre[d] for d in est])
        sa = np.array([self.spy[d] for d in est])
        dar = (ka[1:] / ka[:-1] - 1.0) - (sa[1:] / sa[:-1] - 1.0)
        sigma = float(np.std(dar, ddof=1))
        self.assertAlmostEqual(values["sar"],
                               (raw - spy_r) / (sigma * math.sqrt(19)),
                               places=12)

    def test_7_anchor_session_excluded_from_both_windows(self):
        idx = 500
        base5, _ = self._respond(idx, (-5, -1))
        base20, _ = self._respond(idx, (-20, -1))
        kre2 = dict(self.kre)
        kre2[self.frame[idx]] = kre2[self.frame[idx]] * 3.7  # anchor close
        got5, r5 = j2.timing_response(kre2, self.spy, self.xlf,
                                      self.frame, idx, (-5, -1))
        got20, r20 = j2.timing_response(kre2, self.spy, self.xlf,
                                        self.frame, idx, (-20, -1))
        self.assertIsNone(r5)
        self.assertIsNone(r20)
        self.assertEqual(got5, base5)
        self.assertEqual(got20, base20)

    def test_8_future_sessions_excluded(self):
        idx = 500
        base5, _ = self._respond(idx, (-5, -1))
        kre2 = dict(self.kre)
        for j in range(idx + 1, idx + 30):
            kre2[self.frame[j]] = kre2[self.frame[j]] * 5.0
        got5, r5 = j2.timing_response(kre2, self.spy, self.xlf,
                                      self.frame, idx, (-5, -1))
        self.assertIsNone(r5)
        self.assertEqual(got5, base5)

    def test_9a_missing_history_fails_loud_with_reason(self):
        values, reason = self._respond(64, (-5, -1))
        self.assertIsNone(values)
        self.assertEqual(reason, "insufficient_history_60_before_window")
        values, reason = self._respond(79, (-20, -1))
        self.assertIsNone(values)
        self.assertEqual(reason, "insufficient_history_60_before_window")
        # Exactly at the boundary the response computes.
        values, reason = self._respond(65, (-5, -1))
        self.assertIsNone(reason)
        values, reason = self._respond(80, (-20, -1))
        self.assertIsNone(reason)

    def test_9b_interior_gap_fails_loud(self):
        # Splice a >5 calendar-day hole immediately before the window.
        frame = [d for d in self.frame if not ("2019-06-01" <= d
                                               <= "2019-06-15")]
        idx = next(i for i, d in enumerate(frame) if d >= "2019-07-01")
        values, reason = j2.timing_response(self.kre, self.spy, self.xlf,
                                            frame, idx, (-5, -1))
        self.assertIsNone(values)
        self.assertEqual(reason, "window_gap")

    def test_9c_only_the_two_frozen_windows_exist(self):
        for banned in ((-1, 0), (-3, -1), (-10, -1), (0, 1)):
            with self.assertRaises(ValueError):
                self._respond(400, banned)

    def test_10_event_reference_symmetry(self):
        """Membership is metadata: event and reference values for the same
        anchor session come from the one shared response function."""
        sub = j2.build_state_bearing_substrate(build_timing_fixture())
        # Every available event value equals the direct function output.
        for ev in sub.events:
            if ev["reason"] is not None:
                continue
            direct, reason = j2.timing_response(
                self.kre, self.spy, self.xlf, sub.frame,
                ev["anchor_idx"], (-5, -1))
            self.assertIsNone(reason)
            self.assertEqual(ev["values"], direct)
        # Every reference value equals the direct function output.
        probe = sub.reference_indices[:25]
        for i in probe:
            direct, reason = j2.timing_response(
                self.kre, self.spy, self.xlf, sub.frame, i, (-5, -1))
            self.assertIsNone(reason)
            for metric in j2.METRICS:
                self.assertEqual(
                    sub.reference_values[metric][sub.frame[i]],
                    direct[metric])


# ---------------------------------------------------------------------------
# State-bearing path (protections 11-17)
# ---------------------------------------------------------------------------


class TestStateBearingPath(unittest.TestCase):
    def test_11_mid_rank_rule_reused_exactly(self):
        self.assertIs(j2.mid_rank_percentile, eng.mid_rank_percentile)
        self.assertIs(j2.sorted_abs_percentile, eng._sorted_abs_percentile)

    def test_12_memp_rule_reused_exactly(self):
        self.assertIs(j2.memp, eng.memp)
        self.assertIs(j2.calibration_percentile, eng.calibration_percentile)

    def test_13_calibration_b_is_2000(self):
        self.assertIs(j2.CALIBRATION_B, eng.CALIBRATION_B)
        self.assertEqual(j2.CALIBRATION_B, 2000)

    def test_14_seed_frozen(self):
        self.assertIs(j2.CALIBRATION_SEED, eng.CALIBRATION_SEED)
        self.assertEqual(j2.CALIBRATION_SEED, 20180101)
        res = quiet_result()
        self.assertEqual(res["calibration"]["B"], 2000)
        self.assertEqual(res["calibration"]["seed"], 20180101)
        self.assertEqual(res["calibration"]["rng_policy"],
                         "grouped_shared_calendar_single_stream")

    def test_15_year_matched_without_replacement_shared_calendar(self):
        probe = j2.calibration_placement_probe(build_timing_fixture(), b=7)
        self.assertEqual(probe["group_cells"], (13, 14, 15, 16))
        sub = j2.build_state_bearing_substrate(build_timing_fixture())
        pool = {y: set(v) for y, v in sub.pool_by_year.items()}
        self.assertEqual(len(probe["calendars"]), 7)
        for cal in probe["calendars"]:
            self.assertEqual(len(cal), len(set(cal)))  # without replacement
            counts: dict[str, int] = {}
            for s in cal:
                counts[s[:4]] = counts.get(s[:4], 0) + 1
                self.assertIn(s, pool[s[:4]])
            self.assertEqual(counts, sub.event_year_vector)

    def test_16_node_state_boundaries_reused_exactly(self):
        self.assertIs(j2.classify_node_state, eng.classify_node_state)
        self.assertEqual(j2.classify_node_state(0.6, 0.75),
                         "ORDINARY_UNRESOLVED")
        self.assertEqual(j2.classify_node_state(0.6, 0.76), "ELEVATED")
        self.assertEqual(j2.classify_node_state(0.4, 0.24),
                         "LOWER_MAGNITUDE")
        self.assertEqual(j2.classify_node_state(0.6, 0.24), "DISCORDANT")

    def test_17_overlays_never_rewrite_state(self):
        for res in (quiet_result(), preshock_result()):
            for c in res["cells"]:
                self.assertEqual(
                    c["node_state"],
                    eng.classify_node_state(c["memp"],
                                            c["calibration_percentile"]))
                for k in ("loyo_runs", "loyo_flips", "loeo_runs",
                          "loeo_flips", "f3_reference_n", "f3_memp",
                          "f3_sign_flip"):
                    self.assertIn(k, c)

    def test_17b_engineered_pre_event_shock_elevates_all_four(self):
        res = preshock_result()
        for c in res["cells"]:
            self.assertGreater(c["memp"], 0.5)
            self.assertGreater(c["calibration_percentile"], 0.75)
            self.assertEqual(c["node_state"], "ELEVATED")

    def test_17c_shared_geometry_across_the_four_metrics(self):
        res = quiet_result()
        refs = {c["reference_n"] for c in res["cells"]}
        avail = {c["available_event_n"] for c in res["cells"]}
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(avail), 1)

    def test_17d_f3_uses_span_plus_one_spacing(self):
        sub = j2.build_state_bearing_substrate(build_timing_fixture())
        picks = eng.canonical_disjoint(sub.reference_indices, span=4)
        diffs = [b - a for a, b in zip(picks, picks[1:])]
        self.assertTrue(all(d >= 5 for d in diffs))
        res = quiet_result()
        self.assertEqual(res["cells"][0]["f3_reference_n"], len(picks))

    def test_17e_authorization_is_fail_closed(self):
        with self.assertRaises(eng.AuthorizationError):
            j2.run_state_bearing(build_timing_fixture(), None)
        with self.assertRaises(eng.AuthorizationError):
            j2.run_diagnostics(build_timing_fixture(), None)

    def test_17f_deterministic_rerun(self):
        a = j2.run_state_bearing(build_timing_fixture(), synthetic_auth())
        b = j2.run_state_bearing(build_timing_fixture(), synthetic_auth())
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Diagnostic-only path (protections 18-22)
# ---------------------------------------------------------------------------


class TestDiagnosticOnlyPath(unittest.TestCase):
    BANNED_KEYS = ("memp", "calibration_percentile", "node_state",
                   "placement_year_vector", "loyo_runs", "loyo_flips",
                   "loeo_runs", "loeo_flips", "f3_reference_n", "f3_memp",
                   "f3_change", "f3_sign_flip", "reference_n")

    def test_18_to_21_no_state_bearing_fields(self):
        diag = quiet_diagnostics()
        self.assertEqual(len(diag["diagnostics"]), 4)
        for d in diag["diagnostics"]:
            for k in self.BANNED_KEYS:
                self.assertNotIn(k, d, f"diagnostic carries {k}")
            for k in ("attempted_event_n", "available_event_n",
                      "median_response", "median_abs_response",
                      "direction"):
                self.assertIn(k, d)

    def test_21b_funnel_is_documentation_not_a_reference(self):
        diag = quiet_diagnostics()
        funnel = diag["reference_funnel"]
        self.assertTrue(funnel["frozen_descriptive_only"])
        self.assertIn("eligible_per_year", funnel)
        # Even when the synthetic geometry would leave eligible anchors,
        # the frozen design assigns no reference statistic - the funnel
        # carries counts only.
        self.assertNotIn("memp", json.dumps(funnel))

    def test_22_diagnostics_always_rendered(self):
        text = _render_fixture_report()
        for token in ("D1", "D2", "D3", "D4"):
            self.assertIn(token, text)
        self.assertIn(j2.DIAGNOSTIC_SENTENCE, text)


# ---------------------------------------------------------------------------
# Collision geometry (protections 23-31)
# ---------------------------------------------------------------------------


def _collision_frame() -> tuple[list[str], list[str]]:
    frame = bdays("2020-01-01", 60)
    events = [frame[20], frame[40]]
    return frame, events


class TestCollisionGeometry(unittest.TestCase):
    def test_23_exact_t_tplus1_overlap(self):
        frame, events = _collision_frame()
        # Competing dates resolving to e and e+1 collide.
        for d in (frame[20], frame[21]):
            tags = j2.tag_exact_interval_collisions(frame, events, [d])
            self.assertIn(events[0], tags)
            self.assertNotIn(events[1], tags)
        # A weekend date resolves to the prior session (frozen semantics).
        import datetime as _dt
        sat = (_dt.date.fromisoformat(frame[21])
               + _dt.timedelta(days=(5 - _dt.date.fromisoformat(
                   frame[21]).weekday()) % 7 or 7))
        # Build a Saturday strictly between frame[21] and frame[22] if one
        # exists; otherwise skip (weekday layout dependent).
        if frame[21] < sat.isoformat() < frame[22]:
            tags = j2.tag_exact_interval_collisions(
                frame, events, [sat.isoformat()])
            self.assertIn(events[0], tags)

    def test_24_outside_exact_interval_is_not_a_collision(self):
        frame, events = _collision_frame()
        for d in (frame[19], frame[22], frame[38], frame[43]):
            tags = j2.tag_exact_interval_collisions(frame, events, [d])
            for e, entries in tags.items():
                for entry in entries:
                    self.assertIn(entry["competing_anchor_session"],
                                  (frame[20], frame[21], frame[40],
                                   frame[41]))
            if d in (frame[19], frame[22]):
                self.assertNotIn(events[0], tags)
            if d in (frame[38], frame[43]):
                self.assertNotIn(events[1], tags)

    def test_25_c1_requires_source_pinned_support(self):
        support = j2.c1_macro_register_support()
        self.assertFalse(support["adjudicable"])
        for y in range(2018, 2025):
            self.assertIn(str(y), json.dumps(support["missing_era_years"]))
        self.assertIn("source-pinned", support["reason"])
        # The register builder refuses to mint C1 tags without support.
        frame, events = _collision_frame()
        reg = j2.build_collision_register(
            frame, events, opec_dates=[], c1_support=support)
        self.assertFalse(reg["c1"]["adjudicable"])
        self.assertEqual(reg["c1"]["tags"], {})

    def test_26_c2_uses_the_existing_opec_register(self):
        self.assertIs(j2.build_opec_register, i1.build_opec_register)
        frame, events = _collision_frame()
        reg = j2.build_collision_register(
            frame, events, opec_dates=[frame[21]],
            c1_support={"adjudicable": False, "reason": "unit",
                        "missing_era_years": []})
        self.assertEqual(sorted(reg["c2"]["tags"]), [events[0]])
        entry = reg["c2"]["tags"][events[0]][0]
        self.assertEqual(entry["competing_anchor_session"], frame[21])
        self.assertIn("overlap_basis", entry)

    def test_27_c3_never_excludes(self):
        frame, events = _collision_frame()
        reg = j2.build_collision_register(
            frame, events, opec_dates=[],
            c1_support={"adjudicable": False, "reason": "unit",
                        "missing_era_years": []})
        self.assertFalse(reg["c3"]["excludes"])
        subsets = j2.collision_subsets(reg, events)
        self.assertEqual(subsets["collision_free"]["n"], 2)

    def test_28_primary_denominator_unchanged(self):
        frame, events = _collision_frame()
        reg = j2.build_collision_register(
            frame, events, opec_dates=[frame[21], frame[41]],
            c1_support={"adjudicable": False, "reason": "unit",
                        "missing_era_years": []})
        subsets = j2.collision_subsets(reg, events)
        self.assertEqual(subsets["all"]["n"], len(events))
        self.assertEqual(list(subsets["all"]["dates"]), events)
        res = quiet_result()
        self.assertEqual(res["cells"][0]["attempted_event_n"], 16)

    def test_28b_fomc_self_collision_is_a_checked_invariant(self):
        frame, _ = _collision_frame()
        ok = j2.fomc_self_collision_invariant([10, 20, 30])
        self.assertEqual(ok["violations"], [])
        self.assertEqual(ok["min_anchor_spacing"], 10)
        bad = j2.fomc_self_collision_invariant([10, 11])
        self.assertEqual(len(bad["violations"]), 1)
        with self.assertRaises(j2.J2IntegrityError):
            j2.build_collision_register(
                frame, [frame[10], frame[11]], opec_dates=[],
                c1_support={"adjudicable": False, "reason": "unit",
                            "missing_era_years": []})

    def test_29_subsets_report_exact_n(self):
        frame, events = _collision_frame()
        reg = j2.build_collision_register(
            frame, events, opec_dates=[frame[41]],
            c1_support=j2.c1_macro_register_support())
        subsets = j2.collision_subsets(reg, events)
        self.assertEqual(subsets["all"]["n"], 2)
        self.assertEqual(subsets["c2_tagged"]["n"], 1)
        self.assertEqual(subsets["collision_free"]["n"], 1)
        self.assertEqual(subsets["c1_tagged"]["status"], "unadjudicable")

    def test_30_no_numeric_floor_single_event_subset_executes(self):
        subs, events = raw_group_substrates()
        # Pick an event available in every raw-group cell.
        date = events[3]
        out = j2.subset_reread(subs, (date,), label="unit-single")
        self.assertEqual(out["subset_n"], 1)
        for c in out["cells"]:
            self.assertNotIn("status", c)
            self.assertIsNotNone(c["memp"])
            self.assertEqual(c["available_n"], 1)
            self.assertEqual(c["loeo_runs"], 1)
        import inspect
        src = inspect.getsource(j2)
        self.assertNotIn("MIN_UNIQUE_DATES", src)
        self.assertNotIn("= 11", src)

    def test_31_infeasible_subset_returns_the_frozen_phrase(self):
        self.assertEqual(j2.INSUFFICIENT_SUBSET_PHRASE,
                         "insufficient subset under the frozen procedure")
        subs, _ = raw_group_substrates()
        out = j2.subset_reread(subs, (), label="unit-empty")
        self.assertEqual(out["subset_n"], 0)
        for c in out["cells"]:
            self.assertEqual(c["status"], j2.INSUFFICIENT_SUBSET_PHRASE)

    def test_31b_subset_memp_restricts_only_the_event_set(self):
        subs, events = raw_group_substrates()
        chosen = tuple(events[:4])
        out = j2.subset_reread(subs, chosen, label="unit-4")
        by_cell = {c["cell"]: c for c in out["cells"]}
        sub6 = next(s for s in subs if s.cell["cell"] == 6)
        expected = statistics.median(
            [sub6.event_percentiles[d] for d in chosen
             if d in sub6.event_percentiles])
        self.assertAlmostEqual(by_cell[6]["memp"], expected, places=15)

    def test_31c_subset_calibration_is_reproducible(self):
        subs, events = raw_group_substrates()
        a = j2.subset_reread(subs, tuple(events[:4]), label="unit-4")
        b = j2.subset_reread(subs, tuple(events[:4]), label="unit-4")
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Published-J1B parsing (sensitivity anchor integrity)
# ---------------------------------------------------------------------------


_J1B_SNIPPET = """
| # | measurement | lens | role | M | evid. | events avail/att | ref N | MEMP | calib pct | node state |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | KRE | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | A instrument; B statistic | 64 / 65 | 1797 | 0.664719 | 0.998000 | ELEVATED |
| 2 | IAT | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | B instrument; B statistic | 64 / 65 | 1797 | 0.691987 | 1.000000 | ELEVATED |
"""


class TestPublishedJ1BParsing(unittest.TestCase):
    def test_parse_published_table(self):
        rows = j2.parse_published_j1b_table(_J1B_SNIPPET)
        self.assertEqual(rows[1]["memp"], "0.664719")
        self.assertEqual(rows[1]["calib"], "0.998000")
        self.assertEqual(rows[1]["state"], "ELEVATED")
        self.assertEqual(rows[2]["measurement"], "IAT")

    def test_reproduction_mismatch_fails_loud(self):
        subs, _ = raw_group_substrates()
        published = {s.cell["cell"]: {"memp": "0.999999",
                                      "calib": "0.999999",
                                      "state": "ELEVATED",
                                      "measurement": s.cell["measurement"],
                                      "lens": s.cell["lens"]}
                     for s in subs}
        with self.assertRaises(j2.J2IntegrityError):
            j2.assert_allevents_reproduction(subs, published)


# ---------------------------------------------------------------------------
# Reporting (protections 32-37)
# ---------------------------------------------------------------------------


def _render_fixture_report() -> str:
    if "report" not in _CACHE:
        inputs = build_timing_fixture()
        frame, _, _ = j2.triple_joint_frame(inputs.closes)
        events = list(inputs.event_dates)
        reg = j2.build_collision_register(
            frame, events, opec_dates=[],
            c1_support=j2.c1_macro_register_support())
        subsets = j2.collision_subsets(reg, events)
        subs, sub_events = raw_group_substrates()
        sensitivity = {
            "all": {"label": "all", "quoted_from_published": True},
            "collision_free": j2.subset_reread(
                subs, tuple(sub_events), label="collision_free"),
            "c1_tagged": {"status": "unadjudicable",
                          "reason": "no source-pinned register"},
            "c2_tagged": j2.subset_reread(subs, (), label="c2_tagged"),
        }
        _CACHE["report"] = j2.render_j2_report(
            state_bearing=quiet_result(),
            diagnostics=quiet_diagnostics(),
            register=reg,
            subsets=subsets,
            sensitivity=sensitivity,
            published_j1b=None,
            gate_record={"failure_count": 0,
                         "verifier": "unit",
                         "files": {"g3_price_cache.db":
                                   {"sha256": "aa", "bytes": 1}}},
            provenance={"head": "deadbeef",
                        "timestamp": "2026-07-10T00:00:00Z"},
            conclusions_md="")
    return _CACHE["report"]


class TestReporting(unittest.TestCase):
    def test_32_complete_state_bearing_surface_in_frozen_order(self):
        text = _render_fixture_report()
        pos = [text.find(f"Cell {i} ") for i in (13, 14, 15, 16)]
        self.assertTrue(all(p >= 0 for p in pos))
        self.assertEqual(pos, sorted(pos))

    def test_33_complete_diagnostic_surface(self):
        text = _render_fixture_report()
        pos = [text.find(f"{d} -") for d in ("D1", "D2", "D3", "D4")]
        self.assertTrue(all(p >= 0 for p in pos))
        self.assertEqual(pos, sorted(pos))
        self.assertIn(j2.DIAGNOSTIC_SENTENCE, text)

    def test_34_35_no_sorting_no_ranking(self):
        text = _render_fixture_report().lower()
        for token in ("best", "strongest", "winner", "top-", "ranked",
                      "ranking"):
            self.assertNotIn(token, text)

    def test_36_no_significance_language(self):
        text = _render_fixture_report().lower()
        for token in ("p-value", "signific", "hypothesis test",
                      "confirmed", "validated", "rejected the null",
                      "confidence interval"):
            self.assertNotIn(token, text)
        for token in ("anticipation proof", "leakage", "insider",
                      "causal proof"):
            self.assertNotIn(token, text)

    def test_37_deterministic_report(self):
        a = _render_fixture_report()
        _CACHE.pop("report")
        b = _render_fixture_report()
        self.assertEqual(a, b)

    def test_37b_synthetic_banner_travels(self):
        text = _render_fixture_report()
        self.assertIn(eng.SYNTHETIC_BANNER, text)

    def test_37c_collision_register_language(self):
        text = _render_fixture_report()
        self.assertIn("unadjudicable", text)
        self.assertIn("outside known-register collisions", text)
        self.assertNotIn("free of competing events", text)

    def test_37d_prerun_gate_banner_constant(self):
        self.assertEqual(
            j2.PRERUN_GATE_BANNER,
            "J2 PRE-RUN GATE PASSED — FIRST REAL TIMING EXECUTION "
            "AUTHORIZED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
