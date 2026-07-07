"""J1B live-execution loader/gate tests (Mission J).

All gate/corruption tests run against TEMPORARY fixture snapshots only; the
canonical frozen inputs are never opened by tests that tamper with files.
No real Mission J outcome is computed anywhere in this suite: the engine is
either sentinel-blocked or fed the synthetic J1B fixture.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import g3_mechanical_grinder as g3
from scripts import g_state_acquisition as gsa
from scripts import j1a_data_readiness as j1a
from scripts import j1b_live_execution as live
from scripts import j1b_outcome_engine as eng
from tests.test_j1b_outcome_engine import (bdays, build_fixture,
                                           run_fixture_engine,
                                           synthetic_auth)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_snapshot(tmp: Path) -> None:
    """A tiny j1a-shaped frozen-input snapshot (synthetic values only)."""
    days = bdays("2017-01-03", 40)
    closes = {d: 100.0 + i for i, d in enumerate(days)}

    def pair(m):
        return (dict(m), dict(m))

    g3.build_price_db(tmp / "j1a_price_cache.db",
                      {t: pair(closes) for t in
                       ("SHY", "IAT", "KBE", "VFH")},
                      fetched_at="2026-07-06T00:00:00Z")
    g3.build_price_db(tmp / "g3_price_cache.db",
                      {t: pair(closes) for t in ("KRE", "XLF", "SPY")},
                      fetched_at="2026-07-06T00:00:00Z")
    (tmp / "j1a_price_meta.json").write_text(
        json.dumps({"contract": "tmp-fixture"}), encoding="utf-8")
    two_yr = {d: 2.0 + 0.01 * i for i, d in enumerate(days)}
    # A deliberate one-session hole proves missingness is preserved.
    hole = days[7]
    two_yr.pop(hole)
    spread = {d: 1.0 for d in days}
    j1a.save_treasury_cache(two_yr, spread, {}, tmp / "j1a_treasury.json")


def measure_expectations(tmp: Path) -> dict:
    """j1a-shaped expectations measured from the tmp snapshot."""
    out: dict = {}
    for name in ("j1a_price_cache.db", "g3_price_cache.db",
                 "j1a_price_meta.json", "j1a_treasury.json"):
        p = tmp / name
        exp: dict = {"sha256": _sha(p), "bytes": p.stat().st_size,
                     "kind": "opaque"}
        if name == "j1a_price_cache.db":
            conn = sqlite3.connect(str(p))
            rows = {}
            for t, adj, n, lo, hi in conn.execute(
                    "SELECT ticker, auto_adjust, COUNT(*), MIN(date), "
                    "MAX(date) FROM price_cache GROUP BY ticker, "
                    "auto_adjust"):
                rows[(t, adj)] = (n, lo, hi)
            conn.close()
            exp.update({"kind": "sqlite", "tables": ["price_cache"],
                        "providers": ["yahoo_chart"], "rows": rows})
        if name == "j1a_treasury.json":
            payload = json.loads(p.read_text(encoding="utf-8"))
            series = {}
            for key, data in payload["series"].items():
                dates = sorted(data)
                series[key] = (len(data), dates[0], dates[-1])
            exp.update({"kind": "treasury", "series": series,
                        "duplicate_dates": {}})
        out[name] = exp
    return out


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        build_snapshot(self.tmp)
        self.exp = measure_expectations(self.tmp)

    def _block_loader(self):
        saved = live.load_engine_inputs

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("loader ran before the gate passed")
        live.load_engine_inputs = boom
        self.addCleanup(lambda: setattr(live, "load_engine_inputs", saved))

    def _block_engine(self):
        saved = eng.run_engine

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("engine ran despite gate failure")
        eng.run_engine = boom
        self.addCleanup(lambda: setattr(eng, "run_engine", saved))


class TestRequiredInputSet(unittest.TestCase):
    def test_required_files_match_the_frozen_manifest(self):
        self.assertEqual(sorted(live.REQUIRED_INPUT_FILES),
                         sorted(j1a.FROZEN_INPUTS))
        self.assertEqual(sorted(live.REQUIRED_INPUT_FILES),
                         ["g3_price_cache.db", "j1a_price_cache.db",
                          "j1a_price_meta.json", "j1a_treasury.json"])

    def test_equity_sources_cover_exactly_the_frozen_symbols(self):
        self.assertEqual(sorted(live.LIVE_EQUITY_SOURCES),
                         ["IAT", "KBE", "KRE", "SHY", "SPY", "VFH", "XLF"])
        manifest_equities = {c["measurement"] for c in eng.FROZEN_CELLS
                             if c["lens"] != "raw_change"}
        self.assertTrue(manifest_equities <
                        set(live.LIVE_EQUITY_SOURCES))


class TestGateFailures(SnapshotCase):
    def test_missing_frozen_file_fails(self):
        (self.tmp / "j1a_price_meta.json").unlink()
        self._block_loader()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("j1a_price_meta.json", str(ctx.exception))

    def test_hash_mismatch_fails_before_loading(self):
        p = self.tmp / "j1a_treasury.json"
        data = bytearray(p.read_bytes())
        data[50] ^= 0xFF
        p.write_bytes(bytes(data))
        self._block_loader()
        self._block_engine()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("sha256", str(ctx.exception))

    def test_wrong_file_size_fails(self):
        p = self.tmp / "j1a_price_meta.json"
        p.write_bytes(p.read_bytes() + b" ")
        self._block_loader()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("bytes", str(ctx.exception))

    def test_wrong_sqlite_schema_fails(self):
        p = self.tmp / "j1a_price_cache.db"
        conn = sqlite3.connect(str(p))
        conn.execute("ALTER TABLE price_cache RENAME TO other_table")
        conn.commit(); conn.close()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("tables", str(ctx.exception))

    def test_unexpected_ticker_fails(self):
        conn = sqlite3.connect(str(self.tmp / "j1a_price_cache.db"))
        conn.execute("INSERT INTO price_cache VALUES "
                     "('ZZZ','2017-01-03',1.0,NULL,1,'x','yahoo_chart')")
        conn.commit(); conn.close()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("unexpected", str(ctx.exception))

    def test_missing_ticker_fails(self):
        conn = sqlite3.connect(str(self.tmp / "j1a_price_cache.db"))
        conn.execute("DELETE FROM price_cache WHERE ticker='SHY'")
        conn.commit(); conn.close()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("SHY", str(ctx.exception))

    def test_missing_basis_fails(self):
        conn = sqlite3.connect(str(self.tmp / "j1a_price_cache.db"))
        conn.execute("DELETE FROM price_cache WHERE ticker='VFH' AND "
                     "auto_adjust=1")
        conn.commit(); conn.close()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("VFH", str(ctx.exception))

    def test_row_count_mismatch_fails(self):
        conn = sqlite3.connect(str(self.tmp / "j1a_price_cache.db"))
        conn.execute("DELETE FROM price_cache WHERE ticker='IAT' AND "
                     "auto_adjust=0 AND date='2017-01-20'")
        conn.commit(); conn.close()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("IAT", str(ctx.exception))

    def test_coverage_boundary_mismatch_fails(self):
        conn = sqlite3.connect(str(self.tmp / "j1a_price_cache.db"))
        last = conn.execute("SELECT MAX(date) FROM price_cache WHERE "
                            "ticker='KBE'").fetchone()[0]
        conn.execute("DELETE FROM price_cache WHERE ticker='KBE' AND "
                     "date=?", (last,))
        conn.commit(); conn.close()
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("KBE", str(ctx.exception))

    def test_treasury_count_mismatch_fails(self):
        p = self.tmp / "j1a_treasury.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        first = sorted(payload["series"]["two_yr"])[0]
        payload["series"]["two_yr"].pop(first)
        p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("two_yr", str(ctx.exception))

    def test_treasury_boundary_mismatch_fails(self):
        p = self.tmp / "j1a_treasury.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        last = sorted(payload["series"]["spread_2s10s"])[-1]
        v = payload["series"]["spread_2s10s"].pop(last)
        payload["series"]["spread_2s10s"]["2030-01-02"] = v
        p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("spread_2s10s", str(ctx.exception))

    def test_duplicate_treasury_date_fails(self):
        p = self.tmp / "j1a_treasury.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        payload["meta"]["duplicate_dates"] = {"2017-01-05": 2}
        p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        with self.assertRaises(eng.AuthorizationError) as ctx:
            live.gate_and_load(self.tmp, expectations=self.exp)
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_run_live_blocks_engine_on_any_failure(self):
        (self.tmp / "g3_price_cache.db").unlink()
        self._block_engine()
        with self.assertRaises(eng.AuthorizationError):
            live.run_live(self.tmp, expectations=self.exp)


class TestLoader(SnapshotCase):
    def test_loaded_structure_matches_engine_inputs_contract(self):
        inputs = live.load_engine_inputs(self.tmp)
        self.assertIsInstance(inputs, eng.EngineInputs)
        self.assertFalse(inputs.synthetic)
        self.assertEqual(sorted(inputs.closes),
                         ["IAT", "KBE", "KRE", "SHY", "SPY", "VFH", "XLF"])
        for t, sides in inputs.closes.items():
            self.assertEqual(sorted(sides), ["adjusted", "raw"])
            self.assertTrue(sides["adjusted"] and sides["raw"])
        self.assertEqual(sorted(inputs.treasury),
                         ["spread_2s10s", "two_yr"])
        self.assertEqual(inputs.era, (eng.ERA_START, eng.ERA_END))
        self.assertEqual(len(inputs.event_dates), 65)

    def test_source_dates_and_missingness_preserved(self):
        days = bdays("2017-01-03", 40)
        inputs = live.load_engine_inputs(self.tmp)
        self.assertEqual(sorted(inputs.closes["SHY"]["adjusted"]), days)
        # The engineered Treasury hole is preserved: no interpolation,
        # no forward-fill, no invented observation.
        self.assertNotIn(days[7], inputs.treasury["two_yr"])
        self.assertEqual(len(inputs.treasury["two_yr"]), 39)
        self.assertEqual(len(inputs.treasury["spread_2s10s"]), 40)

    def test_loader_values_are_exact_source_values(self):
        inputs = live.load_engine_inputs(self.tmp)
        self.assertEqual(inputs.closes["KRE"]["raw"]["2017-01-03"], 100.0)
        self.assertEqual(inputs.treasury["spread_2s10s"]["2017-01-03"], 1.0)

    def test_sqlite_opened_read_only(self):
        src = Path(live.__file__).read_text(encoding="utf-8")
        self.assertIn("mode=ro", src)

    def test_canonical_files_unchanged_by_load(self):
        before = {n: _sha(self.tmp / n) for n in live.REQUIRED_INPUT_FILES}
        live.load_engine_inputs(self.tmp)
        after = {n: _sha(self.tmp / n) for n in live.REQUIRED_INPUT_FILES}
        self.assertEqual(before, after)

    def test_no_provider_or_network_call_during_load(self):
        import socket

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("provider/network call during load")
        saved = (gsa._get, g3.fetch_yahoo_ohlc, socket.socket)
        gsa._get = boom
        g3.fetch_yahoo_ohlc = boom
        socket.socket = boom
        try:
            inputs = live.load_engine_inputs(self.tmp)
            self.assertEqual(len(inputs.event_dates), 65)
        finally:
            gsa._get, g3.fetch_yahoo_ohlc, socket.socket = saved

    def test_missing_basis_raises_loader_error(self):
        conn = sqlite3.connect(str(self.tmp / "j1a_price_cache.db"))
        conn.execute("DELETE FROM price_cache WHERE ticker='KBE' AND "
                     "auto_adjust=1")
        conn.commit(); conn.close()
        with self.assertRaises(live.LiveLoadError):
            live.load_engine_inputs(self.tmp)

    def test_deterministic_repeated_load(self):
        a = live.load_engine_inputs(self.tmp)
        b = live.load_engine_inputs(self.tmp)
        self.assertEqual(a.closes, b.closes)
        self.assertEqual(a.treasury, b.treasury)
        self.assertEqual(list(a.event_dates), list(b.event_dates))

    def test_successful_gate_mints_the_only_valid_live_authorization(self):
        auth, inputs, record = live.gate_and_load(self.tmp,
                                                  expectations=self.exp)
        self.assertIsInstance(auth, eng.FrozenInputAuthorization)
        self.assertEqual(record["failure_count"], 0)
        self.assertEqual(sorted(record["files"]),
                         sorted(live.REQUIRED_INPUT_FILES))
        # The engine's own boundary accepts it as a LIVE authorization.
        self.assertFalse(eng._check_authorization(inputs, auth))

    def test_manifest_survives_integration_boundary(self):
        inputs = live.load_engine_inputs(self.tmp)
        for cell in eng.FROZEN_CELLS:
            m, lens = cell["measurement"], cell["lens"]
            if lens == "raw_change":
                key = "two_yr" if m == "2Y_CMT" else "spread_2s10s"
                self.assertIn(key, inputs.treasury)
            else:
                self.assertIn(m, inputs.closes)


class TestEngineExposesUnavailableIdentities(unittest.TestCase):
    def test_cells_carry_unavailable_event_identities(self):
        result = run_fixture_engine()
        cells = eng.result_as_dict(result)["cells"]
        for c in cells:
            self.assertIn("unavailable_events", c)
        beta = next(c for c in cells if c["cell"] == 1)
        self.assertIn(["2018-03-15", "insufficient_history_252_20"],
                      beta["unavailable_events"])


class TestLiveReportRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_fixture_engine()
        cls.record = {
            "failure_count": 0,
            "verifier": "scripts/j1a_data_readiness.py::"
                        "verify_frozen_inputs",
            "files": {"j1a_price_cache.db": {"sha256": "aa", "bytes": 1},
                      "g3_price_cache.db": {"sha256": "bb", "bytes": 2},
                      "j1a_price_meta.json": {"sha256": "cc", "bytes": 3},
                      "j1a_treasury.json": {"sha256": "dd", "bytes": 4}},
        }
        cls.prov = {"head": "deadbeef", "timestamp": "2026-07-07T00:00:00Z"}
        cls.text = live.render_live_report(cls.result, cls.record,
                                           cls.prov, conclusions_md="")

    def test_header_carries_required_provenance(self):
        for token in ("deadbeef", "2026-07-07T00:00:00Z",
                      "grouped_shared_calendar_single_stream",
                      "B = 2000", "seed 20180101", "0 failures",
                      "first real J1B execution",
                      eng.J1B_CONTRACT):
            self.assertIn(token, self.text)

    def test_all_12_cells_in_frozen_order(self):
        pos = [self.text.find(f"| {i} | ") for i in range(1, 13)]
        self.assertTrue(all(p >= 0 for p in pos))
        self.assertEqual(pos, sorted(pos))

    def test_no_ranking_or_hypothesis_test_vocabulary(self):
        for token in ("best", "strongest", "winner", "p-value",
                      "signific", "star"):
            self.assertNotIn(token, self.text.lower())

    def test_no_edge_state_appears(self):
        for token in eng.EDGE_STATE_NAMES:
            self.assertNotIn(token, self.text)

    def test_byte_identical_regeneration(self):
        again = live.render_live_report(self.result, self.record,
                                        self.prov, conclusions_md="")
        self.assertEqual(self.text, again)

    def test_mission_i_comparison_present_with_class_disclosure(self):
        for token in ("Class A", "Class B", "0.674559", "0.725771",
                      "inherited Mission I", "not value-comparable"):
            self.assertIn(token, self.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
