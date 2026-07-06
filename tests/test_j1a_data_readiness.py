"""J1A data-readiness substrate tests (Mission J, j0-v1 contracts).

Outcome-blind by construction: every fixture is synthetic, no network call
is made, no FOMC event-window response value is computed or asserted
anywhere. The tests protect the frozen J0 contracts: the exact 12-cell
manifest, 2s10s panel separation, Treasury 2Y persistence semantics, the
existing provider path for the new ETFs, basis policy, the exact 252/20
rolling-beta geometry with OLS-with-intercept, event/reference symmetry,
deterministic failure reasons, and an outcome-field-free report.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts import j1a_data_readiness as j1a


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def business_days(start_iso: str, n: int) -> list[str]:
    """n weekday ISO dates starting at start_iso (weekends skipped)."""
    out: list[str] = []
    d = date.fromisoformat(start_iso)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def treasury_csv(rows: list[tuple[str, str, str]]) -> bytes:
    """Minimal Treasury daily yield-curve CSV. rows: (mm/dd/yyyy, 2yr, 10yr)."""
    header = 'Date,"1 Mo","2 Yr","10 Yr"\n'
    body = "".join(f'{d},4.00,{v2},{v10}\n' for d, v2, v10 in rows)
    return (header + body).encode("utf-8")


def yahoo_payload(dates: list[str], base: float = 100.0) -> bytes:
    """Minimal Yahoo chart JSON for the given ISO dates (raw + adjclose)."""
    from datetime import datetime, timezone
    stamps = [int(datetime(int(d[:4]), int(d[5:7]), int(d[8:10]),
                           16, tzinfo=timezone.utc).timestamp())
              for d in dates]
    closes = [base + i for i in range(len(dates))]
    payload = {"chart": {"result": [{
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes}],
                       "adjclose": [{"adjclose": closes}]},
    }]}}
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# 1-3. Frozen manifest
# ---------------------------------------------------------------------------


class TestFrozenManifest(unittest.TestCase):
    # The exact J0 section-13 J1 table, frozen order.
    EXPECTED = [
        (1, "KRE", "rolling_beta_ar"),
        (2, "IAT", "rolling_beta_ar"),
        (3, "KBE", "rolling_beta_ar"),
        (4, "XLF", "rolling_beta_ar"),
        (5, "VFH", "rolling_beta_ar"),
        (6, "IAT", "raw_return"),
        (7, "KBE", "raw_return"),
        (8, "XLF", "raw_return"),
        (9, "VFH", "raw_return"),
        (10, "2Y_CMT", "raw_change"),
        (11, "2S10S_CMT", "raw_change"),
        (12, "SHY", "raw_return"),
    ]

    def test_exact_12_cell_manifest_and_order(self):
        got = [(c["cell"], c["measurement"], c["lens"])
               for c in j1a.FROZEN_MANIFEST]
        self.assertEqual(got, self.EXPECTED)

    def test_no_thirteenth_cell(self):
        self.assertEqual(len(j1a.FROZEN_MANIFEST), 12)
        self.assertEqual([c["cell"] for c in j1a.FROZEN_MANIFEST],
                         list(range(1, 13)))

    def test_2s10s_excluded_from_rates_role_panel(self):
        # J0 section 12.2: the curve-shape observable is NOT a rates-panel
        # member and can never contribute to rates-role proxy agreement.
        self.assertNotIn("2S10S_CMT", j1a.RATES_PANEL_MEASUREMENTS)
        self.assertEqual(set(j1a.RATES_PANEL_MEASUREMENTS), {"2Y_CMT", "SHY"})
        cell11 = j1a.FROZEN_MANIFEST[10]
        self.assertEqual(cell11["measurement"], "2S10S_CMT")
        self.assertEqual(cell11["role"], "curve_shape_contextual_layer")
        self.assertNotEqual(cell11["role"], "policy_rates_repricing")

    def test_every_cell_carries_required_metadata(self):
        for c in j1a.FROZEN_MANIFEST:
            for key in ("cell", "measurement", "lens", "role",
                        "evidence_class", "m_class", "source"):
                self.assertIn(key, c, f"cell {c.get('cell')} missing {key}")


# ---------------------------------------------------------------------------
# 4-6. Treasury 2Y persistence semantics
# ---------------------------------------------------------------------------


class TestTreasury2Y(unittest.TestCase):
    def test_2y_persistence_preserves_source_dates_exactly(self):
        rows = [("01/02/2018", "1.92", "2.46"), ("01/03/2018", "1.94", "2.44"),
                ("01/05/2018", "1.96", "2.47")]

        def getter(url, timeout=30):
            return treasury_csv(rows if "2018" in url else [])

        two_yr, spread, dup = j1a.parse_treasury_years(
            getter=getter, years=(2018,),
            start="2018-01-01", end="2018-12-31")
        self.assertEqual(sorted(two_yr),
                         ["2018-01-02", "2018-01-03", "2018-01-05"])
        self.assertEqual(two_yr["2018-01-02"], 1.92)
        self.assertEqual(spread["2018-01-02"], 2.46 - 1.92)

    def test_no_interpolation_or_forward_fill(self):
        # 01/04 absent from the source; an unparseable 2Y on 01/05 stays
        # missing for 2Y while 01/05's presence never back-fills 01/04.
        rows = [("01/02/2018", "1.92", "2.46"), ("01/05/2018", "N/A", "2.47")]

        def getter(url, timeout=30):
            return treasury_csv(rows if "2018" in url else [])

        two_yr, spread, dup = j1a.parse_treasury_years(
            getter=getter, years=(2018,),
            start="2018-01-01", end="2018-12-31")
        self.assertNotIn("2018-01-04", two_yr)
        self.assertNotIn("2018-01-05", two_yr)   # N/A stays missing
        self.assertNotIn("2018-01-05", spread)   # spread needs both legs
        self.assertEqual(sorted(two_yr), ["2018-01-02"])

    def test_duplicate_identical_date_collapses_to_one_observation(self):
        rows = [("01/02/2018", "1.92", "2.46"), ("01/02/2018", "1.92", "2.46")]

        def getter(url, timeout=30):
            return treasury_csv(rows if "2018" in url else [])

        two_yr, spread, dup = j1a.parse_treasury_years(
            getter=getter, years=(2018,),
            start="2018-01-01", end="2018-12-31")
        self.assertEqual(sorted(two_yr), ["2018-01-02"])
        self.assertEqual(dup, {"2018-01-02": 2})

    def test_duplicate_conflicting_date_fails_loudly(self):
        rows = [("01/02/2018", "1.92", "2.46"), ("01/02/2018", "1.93", "2.46")]

        def getter(url, timeout=30):
            return treasury_csv(rows if "2018" in url else [])

        with self.assertRaises(RuntimeError):
            j1a.parse_treasury_years(getter=getter, years=(2018,),
                                     start="2018-01-01", end="2018-12-31")


# ---------------------------------------------------------------------------
# 7-10. ETF provider path and basis policy
# ---------------------------------------------------------------------------


class TestEtfPathAndBasis(unittest.TestCase):
    def test_etf_fetch_uses_existing_yahoo_chart_path(self):
        seen: list[str] = []
        days = business_days("2017-01-03", 5)

        def getter(url, timeout=30):
            seen.append(url)
            return yahoo_payload(days)

        series = j1a.fetch_new_etfs(getter=getter)
        self.assertEqual(sorted(series), ["IAT", "KBE", "SHY", "VFH"])
        self.assertEqual(len(seen), 4)
        for url in seen:
            self.assertIn("query1.finance.yahoo.com/v8/finance/chart/", url)

    def _tmp_db(self, series):
        tmp = tempfile.mkdtemp()
        p = Path(tmp) / "prices.db"
        j1a.g3.build_price_db(p, series, fetched_at="2026-07-06T00:00:00Z")
        return p

    def test_adjusted_adjusted_preference(self):
        days = business_days("2017-01-03", 10)
        closes = {d: 100.0 + i for i, d in enumerate(days)}
        db = self._tmp_db({"AAA": (closes, closes), "SPY": (closes, closes)})
        frame, basis, raw_only = j1a.pair_frame("AAA", db, "SPY", db)
        self.assertEqual(basis, "adjusted")
        self.assertEqual(frame, days)
        self.assertEqual(raw_only, 0)

    def test_raw_only_sessions_disclosed_not_joined(self):
        days = business_days("2017-01-03", 10)
        closes = {d: 100.0 + i for i, d in enumerate(days)}
        adj_missing = dict(closes)
        adj_missing.pop(days[4])  # raw present, adjusted absent on one day
        db = self._tmp_db({"AAA": (closes, adj_missing),
                           "SPY": (closes, closes)})
        frame, basis, raw_only = j1a.pair_frame("AAA", db, "SPY", db)
        self.assertNotIn(days[4], frame)   # never enters the adjusted frame
        self.assertEqual(raw_only, 1)      # disclosed raw/raw fallback count

    def test_cross_basis_sessions_rejected(self):
        # Asset adjusted-only + SPY raw-only on one session: that session is
        # in neither the adjusted-joint nor the raw-joint frame.
        days = business_days("2017-01-03", 10)
        closes = {d: 100.0 + i for i, d in enumerate(days)}
        asset_raw = dict(closes); asset_raw.pop(days[4])
        spy_adj = dict(closes); spy_adj.pop(days[4])
        db = self._tmp_db({"AAA": (asset_raw, closes),
                           "SPY": (closes, spy_adj)})
        frame, basis, raw_only = j1a.pair_frame("AAA", db, "SPY", db)
        self.assertNotIn(days[4], frame)
        self.assertEqual(raw_only, 0)


# ---------------------------------------------------------------------------
# 11-15. Rolling-beta 252/20 geometry and OLS
# ---------------------------------------------------------------------------


class TestRollingBetaGeometry(unittest.TestCase):
    def setUp(self):
        self.frame = business_days("2017-01-03", 300)

    def test_exactly_252_paired_estimation_returns(self):
        r = j1a.beta_readiness(self.frame, 273)
        self.assertTrue(r["ready"])
        self.assertEqual(r["n_estimation_returns"], 252)
        # 253 estimation-sample sessions supply the 252 returns.
        self.assertEqual(r["estimation_first_session"], self.frame[0])
        self.assertEqual(r["estimation_last_session"], self.frame[252])

    def test_exactly_20_session_embargo(self):
        r = j1a.beta_readiness(self.frame, 273)
        self.assertEqual(r["embargo_sessions"], 20)
        self.assertEqual(r["embargo_first_session"], self.frame[253])
        self.assertEqual(r["embargo_last_session"], self.frame[272])

    def test_no_embargo_observation_enters_estimation(self):
        r = j1a.beta_readiness(self.frame, 273)
        self.assertLess(r["estimation_last_session"],
                        r["embargo_first_session"])

    def test_no_future_observation_enters_estimation(self):
        r = j1a.beta_readiness(self.frame, 273)
        self.assertLess(r["estimation_last_session"], self.frame[273])
        self.assertLess(r["embargo_last_session"], self.frame[273])

    def test_ols_includes_intercept(self):
        # y = 0.005 + 2x exactly: an intercept-free fit cannot recover this.
        x = [0.01 * ((i % 5) - 2) for i in range(252)]
        y = [0.005 + 2.0 * v for v in x]
        alpha, beta = j1a.ols_alpha_beta(x, y)
        self.assertAlmostEqual(alpha, 0.005, places=12)
        self.assertAlmostEqual(beta, 2.0, places=12)

    def test_ols_requires_exactly_252_observations(self):
        x = [0.01] * 251
        with self.assertRaises(ValueError):
            j1a.ols_alpha_beta(x, x)

    def test_deterministic_coefficients_from_identical_inputs(self):
        x = [0.01 * ((i * 7 % 11) - 5) for i in range(252)]
        y = [0.002 + 0.8 * v + 0.0001 * ((i * 3 % 7) - 3)
             for i, v in enumerate(x)]
        self.assertEqual(j1a.ols_alpha_beta(x, y), j1a.ols_alpha_beta(x, y))


# ---------------------------------------------------------------------------
# 16-18. Symmetry and deterministic failure reasons
# ---------------------------------------------------------------------------


class TestSymmetryAndFailures(unittest.TestCase):
    def setUp(self):
        self.frame = business_days("2017-01-03", 300)

    def test_identical_anchor_identical_readiness_regardless_of_membership(self):
        as_event = j1a.anchor_readiness(self.frame, 280, "rolling_beta_ar")
        as_reference = j1a.anchor_readiness(self.frame, 280, "rolling_beta_ar")
        self.assertEqual(as_event, as_reference)
        # No membership argument exists at all on the measurement boundary.
        import inspect
        params = inspect.signature(j1a.anchor_readiness).parameters
        self.assertNotIn("membership", params)
        self.assertNotIn("is_event", params)

    def test_insufficient_history_reason(self):
        r = j1a.beta_readiness(self.frame, 272)
        self.assertFalse(r["ready"])
        self.assertEqual(r["failure_reason"], "insufficient_history_252_20")

    def test_no_forward_session_reason(self):
        r = j1a.beta_readiness(self.frame, len(self.frame) - 1)
        self.assertFalse(r["ready"])
        self.assertEqual(r["failure_reason"], "no_forward_session")

    def test_response_window_gap_reason(self):
        frame = business_days("2017-01-03", 299)
        # Splice a >5 calendar-day hole immediately after the anchor.
        gapped = frame[:281] + ["2018-06-01"]
        r = j1a.beta_readiness(gapped, 280)
        self.assertFalse(r["ready"])
        self.assertEqual(r["failure_reason"], "response_window_gap")

    def test_raw_lens_failure_reasons(self):
        frame = business_days("2018-01-02", 50)
        ok = j1a.raw_readiness(frame, 10)
        self.assertTrue(ok["ready"])
        end = j1a.raw_readiness(frame, len(frame) - 1)
        self.assertEqual(end["failure_reason"], "no_forward_session")


# ---------------------------------------------------------------------------
# 19-21. Outcome-blindness of schemas and report determinism
# ---------------------------------------------------------------------------


FORBIDDEN_FIELDS = {"response", "return_value", "abnormal_return", "memp",
                    "percentile", "calibration", "node_state", "edge_state",
                    "alpha", "beta"}


def _all_keys(obj) -> set:
    keys: set = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys |= _all_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            keys |= _all_keys(v)
    return keys


class TestOutcomeBlindness(unittest.TestCase):
    def setUp(self):
        self.frame = business_days("2017-01-03", 300)

    def test_no_outcome_fields_in_readiness_schemas(self):
        r = j1a.beta_readiness(self.frame, 273)
        self.assertFalse(_all_keys(r) & FORBIDDEN_FIELDS)
        r2 = j1a.raw_readiness(self.frame, 10)
        self.assertFalse(_all_keys(r2) & FORBIDDEN_FIELDS)

    def test_no_memp_calibration_or_state_fields_in_cell_funnel(self):
        funnel = self._fixture_funnel()
        self.assertFalse(_all_keys(funnel) & FORBIDDEN_FIELDS)

    def _fixture_funnel(self):
        events = ["2018-03-21", "2018-06-13"]
        return j1a.build_cell_funnel_from_frame(
            cell=j1a.FROZEN_MANIFEST[5],  # IAT raw_return
            frame=business_days("2017-01-03", 600),
            event_dates=events,
            coverage=("2017-01-03", "2019-05-01"),
            basis="adjusted", raw_only=0)

    def test_report_regeneration_is_deterministic(self):
        funnels = [self._fixture_funnel()]
        a = j1a.render_report(funnels, provenance={"fixture": "unit"})
        b = j1a.render_report(funnels, provenance={"fixture": "unit"})
        self.assertEqual(a, b)
        # Value-bearing outcome fields must never appear. (Negated
        # non-claims such as "no MEMP" are required honesty statements.)
        for token in ("MEMP:", "MEMP =", "calibration percentile:",
                      "node state:", "ELEVATED", "abnormal_return"):
            self.assertNotIn(token, a)


# ---------------------------------------------------------------------------
# Funnel symmetry on a real-shaped fixture
# ---------------------------------------------------------------------------


class TestFunnelConstruction(unittest.TestCase):
    def test_event_and_reference_share_gate_machinery(self):
        frame = business_days("2017-01-03", 600)
        events = [frame[300], frame[340]]
        funnel = j1a.build_cell_funnel_from_frame(
            cell=j1a.FROZEN_MANIFEST[0],  # KRE rolling beta
            frame=frame, event_dates=events,
            coverage=(frame[0], frame[-1]), basis="adjusted", raw_only=0)
        ev = funnel["event"]
        ref = funnel["reference"]
        self.assertEqual(ev["attempted"], 2)
        self.assertEqual(ev["ready"], 2)
        # Reference anchors within +-1 session of an event anchor are
        # excluded (buffer = span = 1), and the two event anchors are ready
        # under the identical gate — symmetry is structural.
        self.assertEqual(ref["excluded_event_proximity"], 6)
        self.assertNotIn(300, ref["ready_indices"])
        self.assertNotIn(301, ref["ready_indices"])
        self.assertIn(302, ref["ready_indices"])
        # Identical gate function: an eligible reference index passes the
        # same beta_readiness call the events passed.
        self.assertTrue(j1a.beta_readiness(frame, 302)["ready"])

    def test_reference_era_bounds_respected(self):
        frame = business_days("2017-01-03", 600)
        funnel = j1a.build_cell_funnel_from_frame(
            cell=j1a.FROZEN_MANIFEST[0], frame=frame,
            event_dates=[frame[300]],
            coverage=(frame[0], frame[-1]), basis="adjusted", raw_only=0)
        for idx in funnel["reference"]["ready_indices"]:
            self.assertGreaterEqual(frame[idx], j1a.ERA_START)
            self.assertLessEqual(frame[idx], j1a.ERA_END)


# ---------------------------------------------------------------------------
# Frozen-input snapshot verification (pre-outcome input immutability).
# ---------------------------------------------------------------------------


import hashlib
import shutil
import sqlite3


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class TestFrozenInputs(unittest.TestCase):
    """The J1B input freeze: exact bytes pinned before any outcome exists.

    Corruption cases run on temporary copies only; the canonical frozen
    inputs are never modified by any test in this class.
    """

    @classmethod
    def setUpClass(cls):
        cls.canonical = j1a.CACHE_DIR
        missing = [n for n in j1a.FROZEN_INPUTS
                   if not (cls.canonical / n).exists()]
        if missing:
            raise unittest.SkipTest(
                f"canonical frozen inputs absent locally: {missing}")

    def _tmp_snapshot(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for name in j1a.FROZEN_INPUTS:
            shutil.copy2(self.canonical / name, tmp / name)
        return tmp

    def test_current_frozen_inputs_verify_successfully(self):
        self.assertEqual(j1a.verify_frozen_inputs(self.canonical), [])

    def test_one_byte_change_fails_hash(self):
        tmp = self._tmp_snapshot()
        p = tmp / "j1a_price_cache.db"
        data = bytearray(p.read_bytes())
        data[100] ^= 0xFF  # flip one byte, size unchanged
        p.write_bytes(bytes(data))
        failures = j1a.verify_frozen_inputs(tmp)
        self.assertTrue(any("j1a_price_cache.db" in f and "sha256" in f
                            for f in failures), failures)

    def test_wrong_file_size_fails(self):
        tmp = self._tmp_snapshot()
        p = tmp / "j1a_treasury.json"
        p.write_bytes(p.read_bytes() + b" ")
        failures = j1a.verify_frozen_inputs(tmp)
        self.assertTrue(any("j1a_treasury.json" in f and "bytes" in f
                            for f in failures), failures)

    def test_wrong_ticker_row_count_fails(self):
        tmp = self._tmp_snapshot()
        conn = sqlite3.connect(str(tmp / "j1a_price_cache.db"))
        conn.execute("DELETE FROM price_cache WHERE ticker='SHY' AND "
                     "auto_adjust=1 AND date='2020-06-01'")
        conn.commit(); conn.close()
        failures = j1a.verify_frozen_inputs(tmp)
        self.assertTrue(any("SHY" in f and "adjusted" in f and "2385" in f
                            for f in failures), failures)

    def test_missing_basis_fails(self):
        tmp = self._tmp_snapshot()
        conn = sqlite3.connect(str(tmp / "j1a_price_cache.db"))
        conn.execute("DELETE FROM price_cache WHERE ticker='VFH' AND "
                     "auto_adjust=1")
        conn.commit(); conn.close()
        failures = j1a.verify_frozen_inputs(tmp)
        self.assertTrue(any("VFH" in f and "adjusted" in f
                            for f in failures), failures)

    def test_treasury_count_mismatch_fails(self):
        tmp = self._tmp_snapshot()
        p = tmp / "j1a_treasury.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        first = sorted(payload["series"]["two_yr"])[0]
        payload["series"]["two_yr"].pop(first)
        p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        failures = j1a.verify_frozen_inputs(tmp)
        self.assertTrue(any("two_yr" in f and "2520" in f
                            for f in failures), failures)

    def test_verifier_is_read_only_on_canonical(self):
        before = {n: _sha(self.canonical / n) for n in j1a.FROZEN_INPUTS}
        j1a.verify_frozen_inputs(self.canonical)
        after = {n: _sha(self.canonical / n) for n in j1a.FROZEN_INPUTS}
        self.assertEqual(before, after)

    def test_verifier_never_calls_provider_or_network(self):
        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("network call attempted by verifier")
        saved_get = j1a.gsa._get
        saved_fetch = j1a.g3.fetch_yahoo_ohlc
        j1a.gsa._get = boom
        j1a.g3.fetch_yahoo_ohlc = boom
        try:
            self.assertEqual(j1a.verify_frozen_inputs(self.canonical), [])
        finally:
            j1a.gsa._get = saved_get
            j1a.g3.fetch_yahoo_ohlc = saved_fetch

    def test_j1b_gate_contract_is_explicit(self):
        self.assertIn("before computing any response value",
                      j1a.J1B_INPUT_GATE)
        tmp = self._tmp_snapshot()
        (tmp / "j1a_price_meta.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            j1a.require_frozen_inputs(tmp)
        self.assertIn("j1a_price_meta.json", str(ctx.exception))

    def test_manifest_regeneration_is_deterministic(self):
        a = j1a.render_frozen_manifest()
        b = j1a.render_frozen_manifest()
        self.assertEqual(a, b)
        for name, exp in j1a.FROZEN_INPUTS.items():
            self.assertIn(exp["sha256"], a)
            self.assertIn(name, a)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
