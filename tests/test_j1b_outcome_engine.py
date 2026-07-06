"""J1B pre-outcome engine tests (Mission J, j0-v1 contracts).

Everything here runs on deterministic SYNTHETIC fixtures only. No canonical
J1A input is opened, no provider or network function is reachable from the
engine, and no real Mission J outcome value exists anywhere in this suite.
Synthetic results are engine-verification metadata, never research evidence.
"""

from __future__ import annotations

import json
import math
import statistics
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts import j1b_outcome_engine as eng


# ---------------------------------------------------------------------------
# Deterministic synthetic fixture program
# ---------------------------------------------------------------------------


def bdays(start_iso: str, n: int) -> list[str]:
    out: list[str] = []
    d = date.fromisoformat(start_iso)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _wave(i: int, k: int) -> float:
    """Deterministic pseudo-noise in (-1, 1) without any RNG."""
    return math.sin(0.7 * i + 1.3 * k) * math.cos(0.31 * i - 0.7 * k)


def synth_closes(calendar: list[str], k: int, *, base: float = 100.0,
                 vol: float = 0.01, beta: float = 0.0,
                 bench: list[float] | None = None,
                 event_idx: set[int] | None = None,
                 event_shock: float = 0.0) -> dict[str, float]:
    """Deterministic positive price path with optional benchmark loading
    and optional post-anchor event-window shocks (synthetic only)."""
    px = base
    out = {calendar[0]: px}
    for i in range(1, len(calendar)):
        r = vol * _wave(i, k)
        if bench is not None:
            rb = bench[i] / bench[i - 1] - 1.0
            r += beta * rb
        if event_idx and (i - 1) in event_idx:
            r += event_shock * (1.0 if _wave(i, k) >= 0 else -1.0)
        px *= (1.0 + r)
        out[calendar[i]] = px
    return out


def build_fixture() -> "eng.EngineInputs":
    """Eight era years, two events per year, engineered state variety.

    The calendar starts 2017-03-01 so the first event (2018-03-15) has only
    271 prior sessions - deliberately below the frozen 273-session
    rolling-beta prerequisite - while every raw-lens cell keeps all 16
    events.
    """
    calendar = bdays("2017-03-01", 2470)  # runs well past 2025-12-31
    events = [f"{y}-{m}-15" for y in range(2018, 2026) for m in ("03", "09")]
    spy = synth_closes(calendar, 99, vol=0.009)
    bench_list = [spy[d] for d in calendar]
    ev_idx = set()
    for d in events:
        i = eng.last_index_le(calendar, d)
        assert i is not None
        ev_idx.add(i)

    def both(m):
        return {"adjusted": dict(m), "raw": dict(m)}

    closes = {
        "SPY": both(spy),
        # Strongly shocked at events -> clearly elevated magnitudes.
        "KRE": both(synth_closes(calendar, 1, vol=0.012, beta=1.2,
                                 bench=bench_list, event_idx=ev_idx,
                                 event_shock=0.08)),
        "IAT": both(synth_closes(calendar, 2, vol=0.012, beta=1.1,
                                 bench=bench_list, event_idx=ev_idx,
                                 event_shock=0.06)),
        "KBE": both(synth_closes(calendar, 3, vol=0.012, beta=1.1,
                                 bench=bench_list, event_idx=ev_idx,
                                 event_shock=0.05)),
        # Ordinary: no event shock at all.
        "XLF": both(synth_closes(calendar, 4, vol=0.011, beta=1.0,
                                 bench=bench_list)),
        "VFH": both(synth_closes(calendar, 5, vol=0.011, beta=1.0,
                                 bench=bench_list)),
        "SHY": both(synth_closes(calendar, 6, vol=0.002)),
    }
    # Treasury series on a weekday calendar; 2Y frozen flat at events
    # (lower-magnitude construction), spread ordinary.
    two_yr: dict[str, float] = {}
    spread: dict[str, float] = {}
    lvl2, lvl10 = 2.0, 3.0
    for i, d in enumerate(calendar):
        if (i - 1) not in ev_idx:
            lvl2 += 0.02 * _wave(i, 7)
        lvl10 += 0.02 * _wave(i, 8)
        two_yr[d] = round(lvl2, 6)
        spread[d] = round(lvl10 - lvl2, 6)
    return eng.EngineInputs(
        closes=closes,
        treasury={"two_yr": two_yr, "spread_2s10s": spread},
        event_dates=events,
        synthetic=True)


def synthetic_auth() -> "eng.SyntheticFixtureAuthorization":
    return eng.SyntheticFixtureAuthorization(
        acknowledgement=eng.SYNTHETIC_BANNER)


_RESULT_CACHE: dict = {}


def run_fixture_engine():
    if "result" not in _RESULT_CACHE:
        _RESULT_CACHE["result"] = eng.run_engine(build_fixture(),
                                                 synthetic_auth())
    return _RESULT_CACHE["result"]


# ---------------------------------------------------------------------------
# Manifest and scope
# ---------------------------------------------------------------------------


class TestManifestAndScope(unittest.TestCase):
    EXPECTED = [
        (1, "KRE", "rolling_beta_ar"), (2, "IAT", "rolling_beta_ar"),
        (3, "KBE", "rolling_beta_ar"), (4, "XLF", "rolling_beta_ar"),
        (5, "VFH", "rolling_beta_ar"), (6, "IAT", "raw_return"),
        (7, "KBE", "raw_return"), (8, "XLF", "raw_return"),
        (9, "VFH", "raw_return"), (10, "2Y_CMT", "raw_change"),
        (11, "2S10S_CMT", "raw_change"), (12, "SHY", "raw_return"),
    ]

    def test_exact_12_cell_identity_and_order(self):
        got = [(c["cell"], c["measurement"], c["lens"])
               for c in eng.FROZEN_CELLS]
        self.assertEqual(got, self.EXPECTED)

    def test_no_thirteenth_cell(self):
        self.assertEqual(len(eng.FROZEN_CELLS), 12)

    def test_no_opec_cell(self):
        blob = json.dumps(list(eng.FROZEN_CELLS)).upper()
        for tok in ("OPEC", "XOP", "XLE"):
            self.assertNotIn(tok, blob)

    def test_2s10s_excluded_from_rates_panel(self):
        self.assertEqual(eng.PANELS["policy_rates_repricing"],
                         ("2Y_CMT", "SHY"))
        for members in eng.PANELS.values():
            self.assertNotIn("2S10S_CMT", members)
        self.assertEqual(eng.CONTEXTUAL_MEASUREMENT, "2S10S_CMT")

    def test_frozen_panels(self):
        self.assertEqual(eng.PANELS["balance_sheet_sensitive_second_order"],
                         ("KRE", "IAT", "KBE"))
        self.assertEqual(eng.PANELS["broad_financial_sector"],
                         ("XLF", "VFH"))

    def test_graph_edge_states_absent_from_result_schema(self):
        result = run_fixture_engine()
        blob = json.dumps(eng.result_as_dict(result))
        for token in eng.EDGE_STATE_NAMES:
            self.assertNotIn(token, blob)


# ---------------------------------------------------------------------------
# Execution gate
# ---------------------------------------------------------------------------


class TestExecutionGate(unittest.TestCase):
    def test_no_execution_without_authorization(self):
        with self.assertRaises(eng.AuthorizationError):
            eng.run_engine(build_fixture(), None)

    def test_failed_verification_blocks(self):
        with self.assertRaises(eng.AuthorizationError):
            eng.authorize_from_verification(
                ["j1a_price_cache.db: sha256 mismatch"],
                detail="unit")

    def test_forged_live_authorization_rejected(self):
        forged = eng.FrozenInputAuthorization(detail="forged", _stamp=None)
        with self.assertRaises(eng.AuthorizationError):
            eng.run_engine(build_fixture(), forged)

    def test_synthetic_auth_requires_synthetic_inputs(self):
        inputs = build_fixture()
        object.__setattr__(inputs, "synthetic", False)
        with self.assertRaises(eng.AuthorizationError):
            eng.run_engine(inputs, synthetic_auth())

    def test_live_auth_rejects_synthetic_inputs(self):
        auth = eng.authorize_from_verification([], detail="unit-clean")
        with self.assertRaises(eng.AuthorizationError):
            eng.run_engine(build_fixture(), auth)

    def test_synthetic_auth_requires_exact_banner(self):
        with self.assertRaises(eng.AuthorizationError):
            eng.SyntheticFixtureAuthorization(
                acknowledgement="synthetic-ish").validate()

    def test_engine_imports_no_provider_path(self):
        import scripts.j1b_outcome_engine as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for token in ("urllib", "requests", "http", "sqlite3",
                      "g_state_cache", "fetch_yahoo", "api.stlouisfed",
                      "g_state_acquisition", "g3_mechanical_grinder",
                      "j1a_data_readiness", "event_study_validation"):
            self.assertNotIn(token, src)

    def test_no_runtime_rng_policy_selector_survives(self):
        import inspect
        params = inspect.signature(eng.run_engine).parameters
        self.assertNotIn("rng_policy", params)
        params_c = inspect.signature(eng.calibrate_cells).parameters
        self.assertNotIn("rng_policy", params_c)
        self.assertFalse(hasattr(eng, "RNG_POLICIES"))
        self.assertFalse(hasattr(eng, "CalibrationPolicyError"))
        with self.assertRaises(TypeError):
            eng.run_engine(build_fixture(), synthetic_auth(),
                           rng_policy="anything")  # noqa
        self.assertEqual(eng.CALIBRATION_RNG_POLICY,
                         "grouped_shared_calendar_single_stream")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class TestResponses(unittest.TestCase):
    def setUp(self):
        self.frame = bdays("2017-01-02", 400)

    def test_raw_simple_return_formula(self):
        closes = {d: 100.0 + i for i, d in enumerate(self.frame)}
        v, reason = eng.raw_return_response(closes, self.frame, 10)
        self.assertIsNone(reason)
        self.assertAlmostEqual(v, 111.0 / 110.0 - 1.0, places=15)

    def test_adjusted_adjusted_preference(self):
        m = {d: 100.0 for d in self.frame}
        frame, basis, fallback = eng.matched_basis_frame(
            {"adjusted": m, "raw": m}, {"adjusted": m, "raw": m})
        self.assertEqual(basis, "adjusted")
        self.assertFalse(fallback)

    def test_raw_raw_fallback_disclosed(self):
        m = {d: 100.0 for d in self.frame}
        frame, basis, fallback = eng.matched_basis_frame(
            {"adjusted": None, "raw": m}, {"adjusted": None, "raw": m})
        self.assertEqual(basis, "raw")
        self.assertTrue(fallback)
        self.assertEqual(frame, sorted(m))

    def test_cross_basis_rejected(self):
        m = {d: 100.0 for d in self.frame}
        with self.assertRaises(eng.BasisError):
            eng.matched_basis_frame({"adjusted": m, "raw": None},
                                    {"adjusted": None, "raw": m})

    def test_2y_raw_change_positive_negative_zero(self):
        levels = [1.0, 1.25, 1.10, 1.10]
        for idx, want in ((0, 0.25), (1, -0.15), (2, 0.0)):
            v, reason = eng.raw_change_response(levels, idx)
            self.assertIsNone(reason)
            self.assertAlmostEqual(v, want, places=12)

    def test_raw_change_missing_endpoint(self):
        v, reason = eng.raw_change_response([1.0, 1.1], 1)
        self.assertIsNone(v)
        self.assertEqual(reason, "no_forward_session")

    def test_rolling_beta_exact_estimation_membership(self):
        frame = self.frame[:400]
        bench = {d: 100.0 * (1 + 0.01 * _wave(i, 9)) ** 2 for i, d in
                 enumerate(frame)}
        asset = {d: 50.0 + 0.3 * i for i, d in enumerate(frame)}
        idx = 300
        v, reason, meta = eng.rolling_beta_response(asset, bench, frame, idx)
        self.assertIsNone(reason)
        self.assertEqual(meta["n_estimation_returns"], 252)
        self.assertEqual(meta["estimation_first_session"], frame[idx - 273])
        self.assertEqual(meta["estimation_last_session"], frame[idx - 21])
        self.assertEqual(meta["embargo_first_session"], frame[idx - 20])
        self.assertEqual(meta["embargo_last_session"], frame[idx - 1])

    def test_ols_alpha_beta_with_intercept(self):
        frame = self.frame[:300]
        bench_r = [0.01 * ((i % 7) - 3) for i in range(len(frame) - 1)]
        alpha_true, beta_true = 0.004, 1.7
        bench = [100.0]
        for r in bench_r:
            bench.append(bench[-1] * (1 + r))
        asset = [50.0]
        for r in bench_r:
            asset.append(asset[-1] * (1 + alpha_true + beta_true * r))
        bmap = dict(zip(frame, bench))
        amap = dict(zip(frame, asset))
        idx = 280
        v, reason, meta = eng.rolling_beta_response(amap, bmap, frame, idx)
        self.assertIsNone(reason)
        self.assertAlmostEqual(meta["alpha"], alpha_true, places=10)
        self.assertAlmostEqual(meta["beta"], beta_true, places=10)
        # Event response: AR at i+1 = r_a - (alpha + beta*r_b) == 0 here.
        self.assertAlmostEqual(v, 0.0, places=10)

    def test_rolling_beta_insufficient_history(self):
        frame = self.frame[:300]
        m = {d: 100.0 + i for i, d in enumerate(frame)}
        v, reason, meta = eng.rolling_beta_response(m, m, frame, 272)
        self.assertIsNone(v)
        self.assertEqual(reason, "insufficient_history_252_20")

    def test_rolling_beta_no_future_information(self):
        # Changing any price at or after the anchor must not change
        # alpha/beta (they use only pre-embargo observations).
        frame = self.frame[:400]
        bench_r = [0.01 * _wave(i, 11) for i in range(len(frame) - 1)]
        bench = [100.0]
        for r in bench_r:
            bench.append(bench[-1] * (1 + r))
        asset = [50.0]
        for r in bench_r:
            asset.append(asset[-1] * (1 + 0.5 * r + 0.001 * _wave(len(asset), 12)))
        bmap = dict(zip(frame, bench))
        amap = dict(zip(frame, asset))
        idx = 350
        _, _, meta1 = eng.rolling_beta_response(amap, bmap, frame, idx)
        amap2 = dict(amap)
        for j in range(idx - 20, idx + 2):  # embargo + anchor + forward
            amap2[frame[j]] = amap2[frame[j]] * 3.7
        _, _, meta2 = eng.rolling_beta_response(amap2, bmap, frame, idx)
        self.assertEqual(meta1["alpha"], meta2["alpha"])
        self.assertEqual(meta1["beta"], meta2["beta"])

    def test_event_reference_symmetry_no_membership_argument(self):
        import inspect
        for fn in (eng.raw_return_response, eng.raw_change_response,
                   eng.rolling_beta_response):
            params = inspect.signature(fn).parameters
            self.assertNotIn("membership", params)
            self.assertNotIn("is_event", params)

    def test_same_anchor_same_response_any_label(self):
        closes = {d: 100.0 + 3 * _wave(i, 5) for i, d in
                  enumerate(self.frame)}
        a = eng.raw_return_response(closes, self.frame, 50)
        b = eng.raw_return_response(closes, self.frame, 50)
        self.assertEqual(a, b)


class TestNumericalSafety(unittest.TestCase):
    def setUp(self):
        self.frame = bdays("2017-01-02", 320)

    def test_nan_rejected(self):
        closes = {d: 100.0 for d in self.frame}
        closes[self.frame[100]] = float("nan")
        with self.assertRaises(eng.EngineNumericalError):
            eng.raw_return_response(closes, self.frame, 99)

    def test_inf_rejected(self):
        closes = {d: 100.0 for d in self.frame}
        closes[self.frame[101]] = float("inf")
        with self.assertRaises(eng.EngineNumericalError):
            eng.raw_return_response(closes, self.frame, 100)

    def test_zero_variance_benchmark(self):
        m = {d: 100.0 for d in self.frame}   # constant -> zero variance
        a = {d: 100.0 + i for i, d in enumerate(self.frame)}
        v, reason, meta = eng.rolling_beta_response(a, m, self.frame, 300)
        self.assertIsNone(v)
        self.assertEqual(reason, "zero_variance_benchmark")

    def test_deterministic_coefficients(self):
        bench = {d: 100.0 * (1 + 0.01 * _wave(i, 3)) ** 1 for i, d in
                 enumerate(self.frame)}
        bench = {d: v + i * 0.01 for i, (d, v) in enumerate(bench.items())}
        asset = {d: v * 0.5 + 1 for d, v in bench.items()}
        r1 = eng.rolling_beta_response(asset, bench, self.frame, 300)
        r2 = eng.rolling_beta_response(asset, bench, self.frame, 300)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Mid-rank percentile and MEMP
# ---------------------------------------------------------------------------


class TestMidRankAndMemp(unittest.TestCase):
    def test_below_all(self):
        self.assertEqual(eng.mid_rank_percentile(0.1, [1, 2, 3, 4],
                                                 absolute=True), 0.0)

    def test_above_all(self):
        self.assertEqual(eng.mid_rank_percentile(9.0, [1, 2, 3, 4],
                                                 absolute=True), 1.0)

    def test_single_exact_tie(self):
        # lt=1, eq=1, n=4 -> (1 + 0.5)/4
        self.assertEqual(eng.mid_rank_percentile(2.0, [1, 2, 3, 4],
                                                 absolute=True), 1.5 / 4)

    def test_repeated_ties(self):
        # R = [1,2,2,2,3]; y=2 -> (1 + 1.5)/5
        self.assertEqual(eng.mid_rank_percentile(2.0, [1, 2, 2, 2, 3],
                                                 absolute=True), 2.5 / 5)

    def test_all_equal(self):
        self.assertEqual(eng.mid_rank_percentile(5.0, [5, 5, 5, 5],
                                                 absolute=True), 0.5)

    def test_duplicates_preserved_in_reference(self):
        # [1,2,3,4] -> (1 + 0.5)/4 = 0.375; duplicating the tie changes it
        # to (1 + 1.0)/5 = 0.4 - duplicates are real reference members.
        self.assertEqual(
            eng.mid_rank_percentile(2.0, [1, 2, 3, 4], absolute=True),
            0.375)
        self.assertEqual(
            eng.mid_rank_percentile(2.0, [1, 2, 2, 3, 4], absolute=True),
            0.4)

    def test_absolute_uses_magnitudes(self):
        self.assertEqual(eng.mid_rank_percentile(-3.0, [1, -2, 2.5],
                                                 absolute=True), 1.0)

    def test_memp_odd_even_and_ties(self):
        self.assertEqual(eng.memp([0.2, 0.6, 0.9]), 0.6)
        self.assertEqual(eng.memp([0.2, 0.4, 0.6, 0.9]), 0.5)
        self.assertEqual(eng.memp([0.5, 0.5, 0.5]), 0.5)
        self.assertEqual(eng.memp([0.3, 0.3, 0.7, 0.7]), 0.5)

    def test_memp_matches_statistics_median(self):
        vals = [0.11, 0.93, 0.42, 0.42, 0.77]
        self.assertEqual(eng.memp(vals), statistics.median(vals))


# ---------------------------------------------------------------------------
# Substrate and denominators (via the full fixture)
# ---------------------------------------------------------------------------


class TestSubstrate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_fixture_engine()
        cls.by_cell = {c["cell"]: c for c in
                       eng.result_as_dict(cls.result)["cells"]}

    def test_all_12_cells_have_states(self):
        for i in range(1, 13):
            self.assertIn(self.by_cell[i]["node_state"],
                          ("ELEVATED", "ORDINARY_UNRESOLVED",
                           "LOWER_MAGNITUDE", "DISCORDANT"))

    def test_denominator_preserved_beside_attempted(self):
        for i in range(1, 13):
            c = self.by_cell[i]
            self.assertEqual(c["attempted_event_n"], 16)
            self.assertLessEqual(c["available_event_n"], 16)
            self.assertEqual(sum(c["event_year_vector"].values()),
                             c["available_event_n"])

    def test_rolling_beta_cells_lose_pre_history_events(self):
        # Calendar starts 2016-06-01; the 2018-03-15 event has < 273 prior
        # sessions on this fixture and must be unavailable for beta cells
        # while raw cells keep it.
        beta_n = self.by_cell[1]["available_event_n"]
        raw_n = self.by_cell[6]["available_event_n"]
        self.assertLess(beta_n, raw_n)
        self.assertIn("insufficient_history_252_20",
                      self.by_cell[1]["event_failure_counts"])

    def test_engineered_state_variety_appears(self):
        states = {self.by_cell[i]["node_state"] for i in range(1, 13)}
        self.assertIn("ELEVATED", states)          # shocked bank cells
        self.assertIn("ORDINARY_UNRESOLVED", states)  # unshocked XLF/VFH
        self.assertIn("LOWER_MAGNITUDE", states)   # frozen-at-event 2Y

    def test_no_response_recomputation_in_placement_loop(self):
        self.assertEqual(self.result.metadata["response_evaluations"],
                         self.result.metadata["substrate_response_count"])

    def test_reference_excludes_event_adjacent_sessions(self):
        for i in (6, 10):
            self.assertGreater(self.by_cell[i]["excluded_event_proximity"],
                               0)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


class TestCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_fixture_engine()
        cls.rd = eng.result_as_dict(cls.result)
        cls.by_cell = {c["cell"]: c for c in cls.rd["cells"]}

    def test_b_is_exactly_2000_and_seed_20180101(self):
        self.assertEqual(self.rd["calibration"]["B"], 2000)
        self.assertEqual(self.rd["calibration"]["seed"], 20180101)

    def test_year_count_matching_uses_cell_specific_vector(self):
        # Beta cells lost one 2018 event; their placement year vector must
        # match the AVAILABLE vector, not the attempted one.
        beta = self.by_cell[1]
        raw = self.by_cell[6]
        self.assertNotEqual(beta["event_year_vector"],
                            raw["event_year_vector"])
        self.assertEqual(beta["placement_year_vector"],
                         beta["event_year_vector"])
        self.assertEqual(raw["placement_year_vector"],
                         raw["event_year_vector"])

    def test_placements_without_replacement(self):
        probe = eng.calibration_placement_probe(
            build_fixture(), cell_no=6, b=5)
        for drawn in probe["sessions"]:
            self.assertEqual(len(drawn), len(set(drawn)))

    def test_observed_external_denominator_2000(self):
        # Mid-rank of observed within B placements: denominator exactly B.
        pcts = eng.calibration_percentile(0.5, [0.4] * 1000 + [0.6] * 1000)
        self.assertEqual(pcts, 0.5)
        self.assertEqual(eng.calibration_percentile(0.7, [0.4] * 2000), 1.0)

    def test_mid_rank_tie_semantics_in_calibration(self):
        self.assertEqual(
            eng.calibration_percentile(0.5, [0.4, 0.5, 0.5, 0.6]),
            (1 + 0.5 * 2) / 4)

    def test_deterministic_same_seed(self):
        a = run_fixture_engine()
        b = eng.run_engine(build_fixture(), synthetic_auth())
        self.assertEqual(eng.result_as_dict(a), eng.result_as_dict(b))

    def test_immune_to_global_rng_activity(self):
        import random
        import numpy as np
        random.seed(999)
        np.random.seed(999)
        a = eng.run_engine(build_fixture(), synthetic_auth())
        random.seed(123)
        np.random.seed(123)
        _ = random.random(), np.random.random()
        b = eng.run_engine(build_fixture(), synthetic_auth())
        self.assertEqual(eng.result_as_dict(a), eng.result_as_dict(b))

    def test_pool_shortfall_fails_loudly(self):
        inputs = build_fixture()
        # Decimate 2020 on BOTH Treasury series (keeping their identity
        # sets equal, so group geometry passes) to a 4-session sliver:
        # both 2020 events stay available (anchoring into the sliver),
        # but after the +-1 exclusion the 2020 ordinary pool is empty -
        # the year-matched placement draw cannot execute and must fail
        # loudly.
        def cut(series):
            return {d: v for d, v in series.items()
                    if d[:4] != "2020" or "2020-03-12" <= d <= "2020-03-17"}
        object.__setattr__(
            inputs, "treasury",
            {"two_yr": cut(inputs.treasury["two_yr"]),
             "spread_2s10s": cut(inputs.treasury["spread_2s10s"])})
        with self.assertRaises(eng.CalibrationInfeasibleError):
            eng.run_engine(inputs, synthetic_auth())


# ---------------------------------------------------------------------------
# The frozen grouped_shared_calendar_single_stream policy
# ---------------------------------------------------------------------------


class _FakeSub:
    """Minimal stand-in exposing exactly the geometry the assertion reads."""

    def __init__(self, no, refs, events, years):
        self.cell = {"cell": no}
        self.reference_sessions = list(refs)
        self.available_event_dates = tuple(sorted(events))
        self.event_year_vector = dict(years)


class TestFrozenGroupedCalibration(unittest.TestCase):
    REFS = ["2018-01-02", "2018-01-03", "2019-01-02", "2019-01-03"]
    EVENTS = ("2018-03-15", "2019-03-15")
    YEARS = {"2018": 1, "2019": 1}

    def test_frozen_placement_groups(self):
        self.assertEqual(eng.PLACEMENT_GROUPS, (
            ("rolling_beta_equity", (1, 2, 3, 4, 5)),
            ("raw_etf_returns", (6, 7, 8, 9, 12)),
            ("treasury_rates_geometry", (10, 11)),
        ))

    def test_group2_includes_cell_12_despite_manifest_position(self):
        self.assertIn(12, dict(eng.PLACEMENT_GROUPS)["raw_etf_returns"])
        probe6 = eng.calibration_placement_probe(build_fixture(),
                                                 cell_no=6, b=3)
        probe12 = eng.calibration_placement_probe(build_fixture(),
                                                  cell_no=12, b=3)
        self.assertEqual(probe6["group"], "raw_etf_returns")
        self.assertEqual(probe12["group"], "raw_etf_returns")
        self.assertEqual(probe6["sessions"], probe12["sessions"])

    def test_same_counts_different_ordinary_identities_fail(self):
        a = _FakeSub(6, self.REFS, self.EVENTS, self.YEARS)
        refs2 = self.REFS[:-1] + ["2019-01-04"]  # same count, new identity
        b = _FakeSub(7, refs2, self.EVENTS, self.YEARS)
        with self.assertRaises(eng.CalibrationGeometryError) as ctx:
            eng.assert_group_geometry("unit", [a, b])
        self.assertIn("ordinary-anchor identity", str(ctx.exception))

    def test_same_ordinary_different_event_identities_fail(self):
        a = _FakeSub(6, self.REFS, self.EVENTS, self.YEARS)
        b = _FakeSub(7, self.REFS, ("2018-03-15", "2019-09-15"),
                     self.YEARS)  # same count, different identity
        with self.assertRaises(eng.CalibrationGeometryError) as ctx:
            eng.assert_group_geometry("unit", [a, b])
        self.assertIn("available-event identity", str(ctx.exception))

    def test_same_identities_different_year_vectors_fail(self):
        a = _FakeSub(6, self.REFS, self.EVENTS, self.YEARS)
        b = _FakeSub(7, self.REFS, self.EVENTS, {"2018": 2})
        with self.assertRaises(eng.CalibrationGeometryError) as ctx:
            eng.assert_group_geometry("unit", [a, b])
        self.assertIn("year-count vector", str(ctx.exception))

    def test_all_three_fixture_groups_pass_geometry_and_stream_continues(self):
        # Independent replica of the frozen draw semantics: ONE numpy
        # generator seeded 20180101, groups in frozen order, years
        # ascending, sorted pools, without replacement. The engine's
        # probe (which runs the real grouped sequence) must reproduce
        # every group's calendars exactly - proving group order, shared
        # calendars, draw semantics, and that the stream continues
        # across groups without reset (a reset would make groups 2 and 3
        # match group-1-fresh expectations instead).
        import numpy as np
        inputs = build_fixture()
        b = 4
        subs = {c["cell"]: eng.build_cell_substrate(c, inputs)
                for c in eng.FROZEN_CELLS}
        rng = np.random.default_rng(20180101)
        expected = {}
        for name, cell_nos in eng.PLACEMENT_GROUPS:
            sub0 = subs[cell_nos[0]]
            years = sorted(sub0.event_year_vector)
            arrays = {y: np.array(sub0.pool_by_year[y]) for y in years}
            draws = []
            for _ in range(b):
                drawn = []
                for y in years:
                    pick = rng.choice(arrays[y],
                                      size=sub0.event_year_vector[y],
                                      replace=False)
                    drawn.extend(pick.tolist())
                draws.append(tuple(drawn))
            expected[name] = draws
        for cell_no, gname in ((1, "rolling_beta_equity"),
                               (6, "raw_etf_returns"),
                               (10, "treasury_rates_geometry")):
            probe = eng.calibration_placement_probe(inputs,
                                                    cell_no=cell_no, b=b)
            self.assertEqual(probe["group"], gname)
            self.assertEqual(probe["sessions"], expected[gname],
                             f"group {gname} calendars diverged from the "
                             "frozen single-stream replica")
        # A per-group reset would reproduce group 1's fresh-stream draws
        # in later groups; prove the continuing stream differs from that.
        fresh = np.random.default_rng(20180101)
        sub0 = subs[6]
        years = sorted(sub0.event_year_vector)
        arrays = {y: np.array(sub0.pool_by_year[y]) for y in years}
        fresh_first = []
        for y in years:
            pick = fresh.choice(arrays[y], size=sub0.event_year_vector[y],
                                replace=False)
            fresh_first.extend(pick.tolist())
        self.assertNotEqual(tuple(fresh_first),
                            expected["raw_etf_returns"][0])

    def test_every_cell_in_group_shares_exact_calendar(self):
        inputs = build_fixture()
        probes = [eng.calibration_placement_probe(inputs, cell_no=n, b=2)
                  for n in (1, 2, 3, 4, 5)]
        for p in probes[1:]:
            self.assertEqual(p["sessions"], probes[0]["sessions"])


# ---------------------------------------------------------------------------
# Node states
# ---------------------------------------------------------------------------


class TestNodeStates(unittest.TestCase):
    def test_exact_rules_and_boundaries(self):
        cases = [
            (0.6, 0.76, "ELEVATED"),
            (0.6, 0.75, "ORDINARY_UNRESOLVED"),   # inclusive upper bound
            (0.4, 0.25, "ORDINARY_UNRESOLVED"),   # inclusive lower bound
            (0.6, 0.5, "ORDINARY_UNRESOLVED"),
            (0.4, 0.24, "LOWER_MAGNITUDE"),
            (0.4, 0.76, "DISCORDANT"),
            (0.6, 0.24, "DISCORDANT"),
            (0.5, 0.9, "DISCORDANT"),   # MEMP exactly 0.5, C outside
            (0.5, 0.1, "DISCORDANT"),
            (0.5, 0.5, "ORDINARY_UNRESOLVED"),
        ]
        for m, c, want in cases:
            with self.subTest(m=m, c=c):
                self.assertEqual(eng.classify_node_state(m, c), want)

    def test_partition_exhaustive_and_exclusive(self):
        grid = [i / 40 for i in range(41)]
        for m in grid:
            for c in grid:
                state = eng.classify_node_state(m, c)
                self.assertIn(state, ("ELEVATED", "ORDINARY_UNRESOLVED",
                                      "LOWER_MAGNITUDE", "DISCORDANT"))
                # re-derive: exactly one rule fires
                fires = [
                    m > 0.5 and c > 0.75,
                    0.25 <= c <= 0.75,
                    m < 0.5 and c < 0.25,
                ]
                self.assertEqual(state == "DISCORDANT", not any(fires))

    def test_discordant_cell_constructible(self):
        self.assertEqual(eng.classify_node_state(0.45, 0.99), "DISCORDANT")


# ---------------------------------------------------------------------------
# Panels and modifiers
# ---------------------------------------------------------------------------


class TestPanelModifiers(unittest.TestCase):
    def test_proxy_specific_matches_j0_worked_example(self):
        states = {"KRE": "ELEVATED", "IAT": "ORDINARY_UNRESOLVED",
                  "KBE": "ORDINARY_UNRESOLVED"}
        self.assertEqual(
            eng.role_modifier(("KRE", "IAT", "KBE"), states),
            "PROXY-SPECIFIC")

    def test_role_consistent(self):
        states = {"KRE": "ELEVATED", "IAT": "ELEVATED",
                  "KBE": "ORDINARY_UNRESOLVED"}
        self.assertEqual(
            eng.role_modifier(("KRE", "IAT", "KBE"), states),
            "ROLE-CONSISTENT")

    def test_broad_measurement_consistency(self):
        states = {"2Y_CMT": "LOWER_MAGNITUDE", "SHY": "LOWER_MAGNITUDE"}
        self.assertEqual(eng.role_modifier(("2Y_CMT", "SHY"), states),
                         "BROAD MEASUREMENT CONSISTENCY")

    def test_measurement_disagreement(self):
        states = {"KRE": "ELEVATED", "IAT": "LOWER_MAGNITUDE",
                  "KBE": "DISCORDANT"}
        self.assertEqual(
            eng.role_modifier(("KRE", "IAT", "KBE"), states),
            "MEASUREMENT DISAGREEMENT")

    def test_contextual_cell_never_enters_a_panel(self):
        result = run_fixture_engine()
        rd = eng.result_as_dict(result)
        for role, summary in rd["panel_summaries"].items():
            self.assertNotIn("2S10S_CMT", summary["members"])
        self.assertIn("2S10S_CMT", rd["contextual"]["measurement"])


# ---------------------------------------------------------------------------
# Stability overlays
# ---------------------------------------------------------------------------


class TestOverlays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rd = eng.result_as_dict(run_fixture_engine())
        cls.by_cell = {c["cell"]: c for c in cls.rd["cells"]}

    def test_loyo_removes_events_and_reference_dates(self):
        # Pinned I0 section-15 / I2C-B convention: R shrinks per year.
        probe = eng.loyo_probe(build_fixture(), cell_no=6)
        for year, detail in probe.items():
            self.assertLess(detail["reduced_reference_n"],
                            detail["full_reference_n"])
            self.assertEqual(detail["removed_reference_dates_year"], year)

    def test_loyo_runs_match_era_years(self):
        c = self.by_cell[6]
        self.assertEqual(c["loyo_runs"], 8)

    def test_loeo_removes_one_event_keeps_reference(self):
        probe = eng.loeo_probe(build_fixture(), cell_no=6)
        self.assertEqual(probe["reference_n_constant"], True)
        self.assertEqual(probe["runs"],
                         self.by_cell[6]["available_event_n"])

    def test_f3_canonical_geometry_not_rank_thinning(self):
        # starts >= span+1 apart on eligible indices; for h=1 a dense run
        # of eligible indices halves (ceil), and holes are respected.
        picks = eng.canonical_disjoint(list(range(10)), span=1)
        self.assertEqual(picks, [0, 2, 4, 6, 8])
        picks2 = eng.canonical_disjoint([0, 1, 2, 10, 11, 12], span=1)
        self.assertEqual(picks2, [0, 2, 10, 12])

    def test_f3_reported_per_cell(self):
        c = self.by_cell[6]
        self.assertLess(c["f3_reference_n"], c["reference_n"])
        self.assertIn(c["f3_sign_flip"], (True, False))

    def test_overlays_never_rewrite_state(self):
        # The reported node state must equal the full-sample classification
        # regardless of overlay content.
        for i in range(1, 13):
            c = self.by_cell[i]
            self.assertEqual(
                c["node_state"],
                eng.classify_node_state(c["memp"],
                                        c["calibration_percentile"]))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_fixture_engine()
        cls.text = eng.render_report(cls.result)

    def test_all_12_cells_in_frozen_order(self):
        pos = [self.text.find(f"Cell {i} ") for i in range(1, 13)]
        self.assertTrue(all(p >= 0 for p in pos))
        self.assertEqual(pos, sorted(pos))

    def test_synthetic_banner_present(self):
        self.assertIn(eng.SYNTHETIC_BANNER, self.text)

    def test_no_ranking_or_significance_language(self):
        for token in ("best", "strongest", "rank", "p-value", "signific",
                      "winner", "star"):
            self.assertNotIn(token, self.text.lower())

    def test_no_graph_edge_outcomes(self):
        for token in eng.EDGE_STATE_NAMES:
            self.assertNotIn(token, self.text)

    def test_byte_identical_rerun(self):
        again = eng.render_report(run_fixture_engine())
        self.assertEqual(self.text, again)

    def test_required_fields_present(self):
        for token in ("MEMP", "calibration percentile", "node state",
                      "LOYO", "LOEO", "F3", "available event N",
                      "event-year"):
            self.assertIn(token, self.text)


# ---------------------------------------------------------------------------
# Outcome-contact tripwires
# ---------------------------------------------------------------------------


class TestTripwires(unittest.TestCase):
    def test_engine_runs_with_network_disabled(self):
        import socket
        saved = socket.socket

        def deny(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("network attempted")
        socket.socket = deny
        try:
            r = eng.run_engine(build_fixture(), synthetic_auth())
            self.assertTrue(eng.result_as_dict(r)["synthetic"])
        finally:
            socket.socket = saved

    def test_engine_module_has_no_file_write_calls(self):
        src = Path(eng.__file__).read_text(encoding="utf-8")
        for token in ("write_text", "write_bytes", "open(", "to_csv",
                      "json.dump("):
            self.assertNotIn(token, src)

    def test_result_marked_synthetic_everywhere(self):
        rd = eng.result_as_dict(run_fixture_engine())
        self.assertTrue(rd["synthetic"])
        self.assertIn(eng.SYNTHETIC_BANNER, rd["banner"])


def synthetic_smoke() -> None:  # pragma: no cover - manual smoke entry
    import time
    t0 = time.perf_counter()
    inputs = build_fixture()
    t1 = time.perf_counter()
    result = eng.run_engine(inputs, synthetic_auth())
    t2 = time.perf_counter()
    text = eng.render_report(result)
    t3 = time.perf_counter()
    meta = result.metadata
    print(eng.SYNTHETIC_BANNER)
    print(f"fixture build: {t1 - t0:.2f}s")
    print(f"engine run (substrate + B=2000 x 12 cells): {t2 - t1:.2f}s "
          f"(substrate {meta['substrate_seconds']:.2f}s, "
          f"calibration {meta['calibration_seconds']:.2f}s)")
    print(f"render: {t3 - t2:.2f}s; report chars: {len(text)}")
    states = [(c['cell'], c['node_state'])
              for c in eng.result_as_dict(result)['cells']]
    print("synthetic cell states (engine metadata, not evidence):", states)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--smoke" in sys.argv:
        synthetic_smoke()
    else:
        unittest.main()
