"""Tests for G6B - uniform stability diagnostics over the frozen G6A surface.

Contract under test (task G6B):

* the SAME diagnostics apply to every one of the 120 continuous
  entry x metric x horizon associations (10 continuous entries x 4 metrics
  x 3 horizons) and to every one of the 14 frozen categorical cells - no
  selected subset, no privileged pattern, no winner ranking;
* leave-one-event-out visits every eligible event exactly once and never
  removes an event from the main result; leave-one-year-out visits every
  represented calendar year exactly once;
* the calendar-time confound diagnostic correlates STATE with the event
  date ordinal only - it contains no outcome value;
* Spearman and median calculations are the deterministic G6A/stdlib
  functions (identity reuse, no reimplementation);
* insufficient cells stay visible; credit stays 20/16 era-bounded
  secondary; no pooled FOMC+OPEC statistic; no p-value or significance
  field anywhere;
* the tracked report regenerates byte-identically.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import event_study_validation as esv  # noqa: E402
from scripts import g6_frozen_manifest_readout as g6a  # noqa: E402
from scripts import g6b_stability_falsifiers as g6b  # noqa: E402
from scripts.g3_mechanical_grinder import TRANSMISSION_MAP  # noqa: E402

G4_REPORT = ROOT / "stats" / "G4_STRUCTURAL_FREEZE.md"
LIVE_DB = ROOT / "events.db"
G3_CACHE = ROOT / "g_state_cache" / "g3_price_cache.db"


def _live_ready() -> bool:
    if not (G4_REPORT.exists() and LIVE_DB.exists() and G3_CACHE.exists()):
        return False
    import sqlite3
    con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM g_historical_evidence"
                           ).fetchone()[0] == 97
    except sqlite3.Error:
        return False
    finally:
        con.close()


LIVE_READY = _live_ready()


# ---------------------------------------------------------------------------
# Fixtures: multi-year universe + stub gate (same payload shape as shipped)
# ---------------------------------------------------------------------------


def _fx_row(cid, lane, fam, date, fed, vix, spy, curve, credit):
    lens = TRANSMISSION_MAP[fam]
    return {
        "candidate_id": cid, "denominator_ledger": lane,
        "sampling_family": fam, "source_provenance": "{}",
        "event_date": date, "cutoff": date,
        "mapping_version": "g3-transmission-map-v1",
        "primary_asset": lens.primary, "market_benchmark": lens.market,
        "sector_benchmark": lens.sector,
        "freeze_version": "g4-structural-freeze-v1",
        "state_fed_policy_path": fed, "state_vix_level_percentile": vix,
        "state_spy_trend_ma200": spy, "state_curve_2s10s": curve,
        "state_credit_hy_oas": credit,
        "credit_availability": ("available" if credit is not None
                                else "source_missing"),
        "tag_fed_policy_path": ("easing" if fed < 0 else
                                "hold" if fed == 0 else "tightening"),
        "tag_spy_trend_ma200": "below_ma" if spy < 0 else "above_ma",
        "tag_curve_2s10s": "inverted" if curve < 0 else "non_inverted",
    }


def _fx_rows():
    """Six rows, both lanes, spanning 2023-2025 so LOYO is exercised."""
    specs = [
        ("fomc-a", "frame_complete_historical", "fomc", "2023-03-22",
         0.25, 0.10, 0.02, -0.3, None),
        ("fomc-b", "frame_complete_historical", "fomc", "2024-03-20",
         0.0, 0.40, -0.01, 0.2, 3.4),
        ("fomc-c", "frame_complete_historical", "fomc", "2025-06-18",
         -0.25, 0.80, 0.05, 0.4, 3.1),
        ("opec-a", "designed_contrast", "opec", "2023-06-04",
         0.5, 0.55, 0.01, -0.1, None),
        ("opec-b", "designed_contrast", "opec", "2024-09-05",
         -0.25, 0.90, -0.04, 0.1, 3.3),
        ("opec-c", "designed_contrast", "opec", "2025-04-03",
         -0.5, 0.30, 0.03, 0.5, 2.8),
    ]
    return [_fx_row(*s) for s in specs]


def _stub_gate(event, benchmark_ticker):
    base = (hash((event["event_date"], benchmark_ticker)) % 1000) / 1e4
    return {
        "status": esv.STATUS_AVAILABLE,
        "auto_adjust_basis": {"asset": True, "benchmark": True},
        "per_horizon": [
            {"horizon": h, "raw_return": base + 0.001 * h,
             "benchmark_return": 0.001,
             "abnormal_return": base + 0.0005 * h,
             "sar": base * 10 + 0.01 * h, "car": 99.0}
            for h in (1, 5, 20)],
    }


# ---------------------------------------------------------------------------
# 1. Leave-one-out primitives (hand-verified values)
# ---------------------------------------------------------------------------


class LeaveOneOutTests(unittest.TestCase):
    def test_spearman_and_median_are_identity_reuse(self):
        self.assertIs(g6b.spearman_rho, g6a.spearman_rho)
        self.assertEqual(g6b.median([1.0, 2.0, 4.0]), 2.0)
        self.assertEqual(g6b.median([1.0, 2.0]), 1.5)

    def test_loeo_rho_visits_every_event_once_hand_verified(self):
        out = g6b.loeo_rho([1.0, 2.0, 3.0], [3.0, 1.0, 2.0])
        self.assertEqual(out["runs"], 3)
        self.assertAlmostEqual(out["full"], -0.5)
        self.assertAlmostEqual(out["min"], -1.0)
        self.assertAlmostEqual(out["max"], 1.0)
        self.assertEqual(out["opposite_sign"], 1)
        self.assertAlmostEqual(out["max_abs_change"], 1.5)
        self.assertEqual(out["undefined_runs"], 0)

    def test_loyo_rho_visits_every_year_once_hand_verified(self):
        out = g6b.loyo_rho([1.0, 2.0, 3.0], [3.0, 1.0, 2.0],
                           ["2023", "2023", "2024"])
        self.assertEqual(out["years_tested"], ["2023", "2024"])
        self.assertAlmostEqual(out["min"], -1.0)
        self.assertAlmostEqual(out["max"], -1.0)
        self.assertEqual(out["opposite_sign"], 0)
        self.assertEqual(out["min_retained_n"], 1)
        self.assertEqual(out["undefined_runs"], 1)

    def test_loeo_median_hand_verified(self):
        out = g6b.loeo_median([1.0, 2.0, 3.0])
        self.assertEqual(out, {"runs": 3, "min": 1.5, "max": 2.5})

    def test_loyo_median_hand_verified(self):
        out = g6b.loyo_median([1.0, 2.0, 3.0], ["a", "a", "b"])
        self.assertEqual(out["years_tested"], ["a", "b"])
        self.assertEqual(out["min"], 1.5)
        self.assertEqual(out["max"], 3.0)
        self.assertEqual(out["min_retained_n"], 1)

    def test_inputs_are_never_mutated(self):
        xs, ys = [3.0, 1.0, 2.0], [1.0, 2.0, 3.0]
        g6b.loeo_rho(xs, ys)
        g6b.loyo_rho(xs, ys, ["a", "b", "b"])
        self.assertEqual(xs, [3.0, 1.0, 2.0])
        self.assertEqual(ys, [1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# 2. Board construction on fixtures
# ---------------------------------------------------------------------------


class BoardFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _fx_rows()
        cls.readouts = g6a.compute_readouts(cls.rows, gate=_stub_gate)
        cls.boards = g6b.build_boards(cls.rows, cls.readouts)

    def test_continuous_board_covers_every_association_uniformly(self):
        board = self.boards["continuous"]
        self.assertEqual(len(board), 10 * len(g6a.METRICS)
                         * len(g6a.HORIZONS))
        keys = {(b["lane"], b["state_axis"], b["metric"], b["horizon"])
                for b in board}
        self.assertEqual(len(keys), len(board))
        for b in board:
            for field in ("rho", "loeo", "loyo", "n", "unique_dates"):
                self.assertIn(field, b)

    def test_source_rows_are_never_permanently_altered(self):
        snapshot = copy.deepcopy(self.rows)
        g6b.build_boards(self.rows, self.readouts)
        self.assertEqual(self.rows, snapshot)

    def test_confound_board_has_state_and_date_only(self):
        board = self.boards["confound"]
        self.assertEqual(len(board), 10)  # 2 lanes x 5 axes
        for b in board:
            self.assertEqual(set(b), {"lane", "state_axis", "n",
                                      "rho_state_vs_date_ordinal"})
        dumped = json.dumps(board).lower()
        for banned in ("return", "sar", "abnormal", "outcome"):
            self.assertNotIn(banned, dumped)

    def test_confound_detects_state_tracking_time(self):
        # fed_policy_path decreases monotonically with date in BOTH fixture
        # lanes -> rho must be -1 there.
        vals = {(b["lane"], b["state_axis"]):
                b["rho_state_vs_date_ordinal"]
                for b in self.boards["confound"]}
        self.assertAlmostEqual(
            vals[("frame_complete_historical", "fed_policy_path")], -1.0)
        self.assertAlmostEqual(
            vals[("designed_contrast", "fed_policy_path")], -1.0)

    def test_categorical_board_has_14_cells_with_thin_visible(self):
        board = self.boards["categorical"]
        self.assertEqual(len(board), 14)
        for cell in board:
            self.assertEqual(cell["support"], "insufficient_n")  # tiny fx
            self.assertIn("per_metric", cell)

    def test_consistency_board_counts_signs_without_ranking(self):
        board = self.boards["consistency"]
        self.assertEqual(len(board), 10)
        for e in board:
            s = e["sign_counts"]
            self.assertEqual(s["positive"] + s["zero"] + s["negative"], 12)
            self.assertNotIn("score", json.dumps(e).lower())
            self.assertNotIn("rank", json.dumps(e).lower())

    def test_no_pooled_statistic_and_no_significance_fields(self):
        dumped = json.dumps(self.boards).lower()
        for banned in ("pooled", "p_value", "pvalue", "significan",
                       "confidence", "pearson"):
            self.assertNotIn(banned, dumped, banned)

    def test_boards_are_deterministic(self):
        again = g6b.build_boards(list(reversed(self.rows)),
                                 dict(self.readouts))
        self.assertEqual(self.boards, again)


# ---------------------------------------------------------------------------
# 3. Live run (real surface; reused G6A contracts)
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_READY, "promoted rows + G4 report + cache needed")
class LiveStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = g6b.run_stability()

    def test_exactly_120_continuous_associations(self):
        self.assertEqual(len(cls_board := self.result["boards"]
                             ["continuous"]), 120)
        self.assertEqual(sum(1 for b in cls_board
                             if b["lane"] == "frame_complete_historical"),
                         60)

    def test_g6a_denominators_and_credit_subsets_unchanged(self):
        ns = {(b["lane"], b["state_axis"]): b["n"]
              for b in self.result["boards"]["continuous"]}
        self.assertEqual(ns[("frame_complete_historical",
                             "credit_hy_oas")], 20)
        self.assertEqual(ns[("designed_contrast", "credit_hy_oas")], 16)
        self.assertEqual(ns[("frame_complete_historical",
                             "fed_policy_path")], 65)
        self.assertEqual(ns[("designed_contrast", "curve_2s10s")], 32)

    def test_exactly_14_categorical_cells_thin_ones_visible(self):
        board = self.result["boards"]["categorical"]
        self.assertEqual(len(board), 14)
        thin = {(c["lane"], c["state_axis"], c["cell"]): c["support"]
                for c in board if c["support"] == "insufficient_n"}
        self.assertEqual(set(thin), {
            ("designed_contrast", "curve_2s10s", "inverted"),
            ("designed_contrast", "fed_policy_path", "tightening"),
            ("designed_contrast", "spy_trend_ma200", "below_ma")})

    def test_report_regenerates_byte_identically(self):
        artifact = ROOT / "stats" / "G6B_STABILITY_AND_FALSIFIERS.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         g6b.build_report_text())

    def test_report_states_120_and_names_falsifier_uniformity(self):
        text = g6b.build_report_text()
        self.assertIn("120", text)
        self.assertIn("same diagnostics as every other association", text)


if __name__ == "__main__":
    unittest.main()
