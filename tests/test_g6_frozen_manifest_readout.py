"""Tests for G6A - execution of the frozen G4 comparison manifest.

Contract under test (G0 protocol s14; G4 freeze; task G6A):

* the evidence universe is EXACTLY the 97 promoted `g_historical_evidence`
  rows (65 frame + 32 designed); the accepted 86 and every other archive
  row are excluded by construction and the loader reads only the G5
  whitelist columns;
* the 16 frozen manifest entries are executed exactly - no extra axis, no
  extra entry, no pooled FOMC+OPEC output; drift against the tracked G4
  contract fails loudly;
* outcomes come from the SHIPPED event-study gate (canonical vs SPY and
  sector-relative vs the family ETF) under the frozen transmission map;
  exactly four metrics x three shipped horizons; CAR is present in the
  gate payload and is deliberately NOT extracted;
* descriptive statistics are deterministic (inclusive-method quartiles,
  tie-aware Spearman on ranks, exact sign counts); no p-value, no
  significance label, no Pearson, no binning of continuous axes;
* the frozen structural floor (11 unique dates) marks thin cells
  `insufficient_n` while keeping them fully visible;
* the tracked report regenerates byte-identically.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import event_study_validation as esv  # noqa: E402
from scripts import g4_structural_freeze as g4  # noqa: E402
from scripts import g6_frozen_manifest_readout as g6  # noqa: E402
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
        n = con.execute(
            "SELECT COUNT(*) FROM g_historical_evidence").fetchone()[0]
        return n == 97
    except sqlite3.Error:
        return False
    finally:
        con.close()


LIVE_READY = _live_ready()


# ---------------------------------------------------------------------------
# Fixtures: a tiny promoted universe (both lanes, credit mixed) + stub gate
# ---------------------------------------------------------------------------


def _fx_row(cid, lane, fam, date, cutoff, fed, vix, spy, curve, credit):
    lens = TRANSMISSION_MAP[fam]
    return {
        "candidate_id": cid, "denominator_ledger": lane,
        "sampling_family": fam, "source_provenance": "{}",
        "event_date": date, "cutoff": cutoff,
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
    rows = []
    specs = [
        ("fomc-a", "frame_complete_historical", "fomc", "2024-01-10",
         -0.25, 0.10, 0.02, -0.3, 3.5),
        ("fomc-b", "frame_complete_historical", "fomc", "2024-03-20",
         0.0, 0.40, -0.01, 0.2, None),
        ("fomc-c", "frame_complete_historical", "fomc", "2024-06-12",
         0.25, 0.80, 0.05, 0.4, 3.1),
        ("opec-a", "designed_contrast", "opec", "2024-02-04",
         -0.25, 0.55, 0.01, -0.1, 3.3),
        ("opec-b", "designed_contrast", "opec", "2024-09-05",
         0.5, 0.90, -0.04, 0.1, None),
    ]
    for cid, lane, fam, date, fed, vix, spy, curve, credit in specs:
        rows.append(_fx_row(cid, lane, fam, date, f"{date[:8]}01",
                            fed, vix, spy, curve, credit))
    return rows


def _stub_gate(seed_shift=0.0):
    """A stand-in for the shipped gate returning a valid AVAILABLE payload;
    values are a deterministic function of (event_date, benchmark)."""
    def gate(event, benchmark_ticker):
        base = (hash((event["event_date"], benchmark_ticker)) % 1000) / 1e4
        per = {}
        for h in (1, 5, 20):
            per[h] = {"raw_return": base + 0.001 * h + seed_shift,
                      "benchmark_return": 0.001,
                      "abnormal_return": base + 0.0005 * h,
                      "sar": (base * 10) + 0.01 * h,
                      "car": 99.0}   # present in payload, must NOT leak
        return {
            "status": esv.STATUS_AVAILABLE,
            "auto_adjust_basis": {"asset": True, "benchmark": True},
            "per_horizon": [
                {"horizon": h, **per[h]} for h in (1, 5, 20)],
        }
    return gate


# ---------------------------------------------------------------------------
# 1. Deterministic descriptive statistics
# ---------------------------------------------------------------------------


class DescriptiveStatsTests(unittest.TestCase):
    def test_quantiles_are_inclusive_method_and_deterministic(self):
        q = g6.five_number_summary([4.0, 1.0, 3.0, 2.0])
        self.assertEqual(q, {"min": 1.0, "p25": 1.75, "median": 2.5,
                             "p75": 3.25, "max": 4.0})
        self.assertEqual(g6.five_number_summary([7.0]),
                         {"min": 7.0, "p25": 7.0, "median": 7.0,
                          "p75": 7.0, "max": 7.0})

    def test_sign_counts_treat_exact_zero_separately(self):
        self.assertEqual(g6.sign_counts([0.5, -0.2, 0.0, 0.1]),
                         {"positive": 2, "zero": 1, "negative": 1})

    def test_spearman_perfect_monotone_is_one(self):
        self.assertAlmostEqual(
            g6.spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(
            g6.spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_spearman_handles_ties_with_average_ranks(self):
        rho = g6.spearman_rho([1.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(rho, 0.9486832980505138, places=12)

    def test_spearman_degenerate_inputs_return_none(self):
        self.assertIsNone(g6.spearman_rho([1.0], [2.0]))
        self.assertIsNone(g6.spearman_rho([2.0, 2.0, 2.0], [1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# 2. Gate reuse and metric extraction (stub gate; no parallel engine)
# ---------------------------------------------------------------------------


class ReadoutExtractionTests(unittest.TestCase):
    def test_metrics_extracted_from_shipped_payload_shape(self):
        rows = _fx_rows()
        readouts = g6.compute_readouts(rows, gate=_stub_gate())
        self.assertEqual(set(readouts), {r["candidate_id"] for r in rows})
        one = readouts["fomc-a"]
        self.assertEqual(set(one["metrics"]), set(g6.METRICS))
        for metric in g6.METRICS:
            self.assertEqual(set(one["metrics"][metric]), {1, 5, 20})
        self.assertEqual(one["basis"], "adjusted")

    def test_car_and_extra_metrics_never_leak(self):
        readouts = g6.compute_readouts(_fx_rows(), gate=_stub_gate())
        dumped = json.dumps(readouts).lower()
        self.assertNotIn("car", dumped.replace("carry", ""))
        self.assertNotIn("scar", dumped)
        self.assertNotIn("pearson", dumped)

    def test_horizons_are_exactly_the_shipped_triple(self):
        self.assertEqual(g6.HORIZONS, (1, 5, 20))
        self.assertIs(g6.HORIZONS, tuple(g6.HORIZONS))
        self.assertEqual(tuple(esv.HORIZONS), g6.HORIZONS)

    def test_non_adjusted_basis_fails_loudly(self):
        def raw_gate(event, benchmark_ticker):
            out = _stub_gate()(event, benchmark_ticker)
            out["auto_adjust_basis"] = {"asset": False, "benchmark": False}
            out["basis_fallback"] = "matched_raw_fallback"
            return out
        with self.assertRaises(ValueError) as ctx:
            g6.compute_readouts(_fx_rows(), gate=raw_gate)
        self.assertIn("basis", str(ctx.exception))

    def test_unavailable_gate_status_fails_loudly(self):
        def dead_gate(event, benchmark_ticker):
            return {"status": "insufficient_data"}
        with self.assertRaises(ValueError):
            g6.compute_readouts(_fx_rows(), gate=dead_gate)


# ---------------------------------------------------------------------------
# 3. Manifest derivation, reconciliation, and pooling bans
# ---------------------------------------------------------------------------


class ManifestShapeTests(unittest.TestCase):
    def test_fixture_universe_derives_exactly_16_entries(self):
        entries = g6.derive_manifest_entries(_fx_rows())
        self.assertEqual(len(entries), 16)
        per_lane: dict[str, int] = {}
        for e in entries:
            per_lane[e["lane"]] = per_lane.get(e["lane"], 0) + 1
            self.assertIn(e["state_axis"], g6.CONTINUOUS_AXES)
        self.assertEqual(per_lane, {"frame_complete_historical": 8,
                                    "designed_contrast": 8})
        uses = {(e["lane"], e["state_axis"], e["use"]) for e in entries}
        self.assertEqual(len(uses), 16)

    def test_no_pooled_entry_and_no_mechanism_axis(self):
        entries = g6.derive_manifest_entries(_fx_rows())
        dumped = json.dumps(entries).lower()
        for banned in ("pooled", "mechanism", "taxonomy", "j1", "overlay"):
            self.assertNotIn(banned, dumped, banned)

    def test_manifest_reconciliation_raises_on_denominator_drift(self):
        entries = g6.derive_manifest_entries(_fx_rows())
        frozen = [dict(e) for e in entries]
        frozen[3]["eligible_denominator"] += 1
        with self.assertRaises(ValueError):
            g6.reconcile_manifest(entries, frozen)
        g6.reconcile_manifest(entries, [dict(e) for e in entries])

    def test_seventeenth_entry_fails_reconciliation(self):
        entries = g6.derive_manifest_entries(_fx_rows())
        with self.assertRaises(ValueError):
            g6.reconcile_manifest(entries + [dict(entries[0])], entries)


# ---------------------------------------------------------------------------
# 4. Summaries: continuous never binned; categorical cells frozen; floor 11
# ---------------------------------------------------------------------------


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.rows = _fx_rows()
        self.readouts = g6.compute_readouts(self.rows, gate=_stub_gate())

    def test_support_floor_is_the_frozen_g4_constant(self):
        self.assertEqual(g6.MIN_CELL_UNIQUE_DATES, 11)
        self.assertIs(g6.MIN_CELL_UNIQUE_DATES, g4.MIN_CELL_UNIQUE_DATES)

    def test_continuous_summary_reports_all_required_fields(self):
        frame = [r for r in self.rows
                 if r["denominator_ledger"] == "frame_complete_historical"]
        s = g6.summarize_continuous(frame, "state_fed_policy_path",
                                    self.readouts)
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["unique_dates"], 3)
        self.assertEqual(set(s["state_summary"]),
                         {"min", "p25", "median", "p75", "max"})
        block = s["per_metric"]["spy_relative_ar"][5]
        for key in ("mean", "median", "p25", "p75", "min", "max",
                    "positive", "zero", "negative", "spearman_rho"):
            self.assertIn(key, block)
        self.assertNotIn("p_value", json.dumps(s))
        self.assertNotIn("bins", json.dumps(s))

    def test_categorical_summary_keeps_thin_cells_visible(self):
        frame = [r for r in self.rows
                 if r["denominator_ledger"] == "frame_complete_historical"]
        s = g6.summarize_categorical(frame, "tag_fed_policy_path",
                                     ("easing", "hold", "tightening"),
                                     self.readouts)
        self.assertEqual(set(s["cells"]), {"easing", "hold", "tightening"})
        for cell in s["cells"].values():
            self.assertEqual(cell["support"], "insufficient_n")
            self.assertIn("per_metric", cell)  # outcomes shown regardless
        self.assertEqual(s["cells"]["easing"]["n"], 1)

    def test_credit_summary_uses_only_available_subset(self):
        frame = [r for r in self.rows
                 if r["denominator_ledger"] == "frame_complete_historical"]
        s = g6.summarize_continuous(frame, "state_credit_hy_oas",
                                    self.readouts)
        self.assertEqual(s["n"], 2)  # one frame row is source_missing

    def test_full_build_is_deterministic(self):
        b1 = g6.build_readout(self.rows, self.readouts)
        b2 = g6.build_readout(list(reversed(self.rows)),
                              dict(self.readouts))
        self.assertEqual(b1, b2)


# ---------------------------------------------------------------------------
# 5. Live execution (real promoted rows, real gate, real price cache)
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_READY, "promoted rows, G4 report, g3 cache needed")
class LiveManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = g6.load_promoted_rows()

    def test_universe_is_exactly_the_97_promoted_rows(self):
        recon = g6.reconcile_universe(self.rows)
        self.assertEqual(recon["frame_complete_historical"], 65)
        self.assertEqual(recon["designed_contrast"], 32)
        self.assertEqual(recon["total"], 97)
        self.assertEqual(recon["unique_candidate_ids"], 97)
        self.assertEqual(recon["unique_event_dates"], 97)

    def test_loader_reads_only_promoted_ledger_rows(self):
        for r in self.rows:
            self.assertIn(r["denominator_ledger"],
                          ("frame_complete_historical",
                           "designed_contrast"))
            self.assertTrue(r["candidate_id"].startswith(("fomc-", "opec-")))
        self.assertEqual(set(r.keys()) - set(g6.PROMOTED_COLUMNS), set())

    def test_derived_manifest_matches_frozen_g4_contract(self):
        derived = g6.derive_manifest_entries(self.rows)
        frozen = g6.parse_frozen_manifest(
            G4_REPORT.read_text(encoding="utf-8"))
        g6.reconcile_manifest(derived, frozen)  # must not raise
        self.assertEqual(len(derived), 16)
        by_key = {(e["lane"], e["state_axis"], e["use"]):
                  e["eligible_denominator"] for e in derived}
        self.assertEqual(
            by_key[("frame_complete_historical", "credit_hy_oas",
                    "continuous")], 20)
        self.assertEqual(
            by_key[("designed_contrast", "credit_hy_oas", "continuous")],
            16)

    def test_report_regenerates_byte_identically(self):
        artifact = ROOT / "stats" / "G6_FROZEN_MANIFEST_READOUT.md"
        if not artifact.exists():
            self.skipTest("readout not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         g6.build_report_text())


if __name__ == "__main__":
    unittest.main()
