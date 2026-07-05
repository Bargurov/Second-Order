"""Tests for G6C - state-anchored representative cases.

Contract under test (task G6C):

* exactly six role slots from exactly three frozen role definitions
  (OPEC fed_policy_path over the 32 designed rows; OPEC credit_hy_oas over
  the 16-row credit-available subset; FOMC fed_policy_path over the 65
  frame rows), each selecting a Q25 and a Q75 state-anchor case;
* anchors reuse the G6A inclusive quantile convention (identity, not a
  re-implementation); selection minimizes |state - target| with the
  frozen tie-break (event date ascending, then candidate id ascending);
* outcome values CANNOT enter selection: the selector never sees
  readouts, and perturbing outcomes cannot change the selected ids;
* a candidate selected by two roles keeps both role assignments and is
  rendered once - never silently substituted;
* case provenance comes only from the existing G1 ledgers;
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
from scripts import g6_frozen_manifest_readout as g6a  # noqa: E402
from scripts import g6c_representative_cases as g6c  # noqa: E402
from scripts.g3_mechanical_grinder import TRANSMISSION_MAP  # noqa: E402

G1A = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"
LIVE_DB = ROOT / "events.db"
G3_CACHE = ROOT / "g_state_cache" / "g3_price_cache.db"


def _live_ready() -> bool:
    if not (G1A.exists() and G1B.exists() and LIVE_DB.exists()
            and G3_CACHE.exists()):
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


def _fx_row(cid, lane, fam, date, fed, credit):
    lens = TRANSMISSION_MAP[fam]
    return {
        "candidate_id": cid, "denominator_ledger": lane,
        "sampling_family": fam, "source_provenance": "{}",
        "event_date": date, "cutoff": date,
        "mapping_version": "g3-transmission-map-v1",
        "primary_asset": lens.primary, "market_benchmark": lens.market,
        "sector_benchmark": lens.sector,
        "freeze_version": "g4-structural-freeze-v1",
        "state_fed_policy_path": fed, "state_vix_level_percentile": 0.5,
        "state_spy_trend_ma200": 0.01, "state_curve_2s10s": 0.1,
        "state_credit_hy_oas": credit,
        "credit_availability": ("available" if credit is not None
                                else "source_missing"),
        "tag_fed_policy_path": ("easing" if fed < 0 else
                                "hold" if fed == 0 else "tightening"),
        "tag_spy_trend_ma200": "above_ma",
        "tag_curve_2s10s": "non_inverted",
    }


def _fx_rows():
    """OPEC states 0..4 (credit on three of them), FOMC states 0..4."""
    rows = []
    for i in range(5):
        rows.append(_fx_row(f"opec-x{i}", "designed_contrast", "opec",
                            f"2024-0{i + 1}-10", float(i),
                            3.0 + i if i < 3 else None))
        rows.append(_fx_row(f"fomc-x{i}", "frame_complete_historical",
                            "fomc", f"2024-0{i + 1}-20", float(i), None))
    return rows


class RoleContractTests(unittest.TestCase):
    def test_exactly_three_frozen_roles_and_six_slots(self):
        self.assertEqual(len(g6c.ROLES), 3)
        by_role = {r["role"]: r for r in g6c.ROLES}
        self.assertEqual(by_role["A"]["lane"], "designed_contrast")
        self.assertEqual(by_role["A"]["state_axis"], "fed_policy_path")
        self.assertEqual(by_role["A"]["subset"], "all")
        self.assertEqual(by_role["B"]["lane"], "designed_contrast")
        self.assertEqual(by_role["B"]["state_axis"], "credit_hy_oas")
        self.assertEqual(by_role["B"]["subset"], "credit_available")
        self.assertEqual(by_role["C"]["lane"], "frame_complete_historical")
        self.assertEqual(by_role["C"]["state_axis"], "fed_policy_path")
        slots = g6c.select_cases(_fx_rows())
        self.assertEqual(len(slots), 6)
        self.assertEqual([s["quantile"] for s in slots],
                         ["q25", "q75"] * 3)

    def test_anchors_reuse_g6a_inclusive_quantiles(self):
        slots = g6c.select_cases(_fx_rows())
        opec_states = [0.0, 1.0, 2.0, 3.0, 4.0]
        summary = g6a.five_number_summary(opec_states)
        a25 = next(s for s in slots if s["role"] == "A"
                   and s["quantile"] == "q25")
        a75 = next(s for s in slots if s["role"] == "A"
                   and s["quantile"] == "q75")
        self.assertEqual(a25["target"], summary["p25"])
        self.assertEqual(a75["target"], summary["p75"])
        self.assertEqual(a25["candidate_id"], "opec-x1")  # state 1.0
        self.assertEqual(a75["candidate_id"], "opec-x3")  # state 3.0

    def test_role_b_universe_is_credit_available_only(self):
        slots = g6c.select_cases(_fx_rows())
        b_ids = {s["candidate_id"] for s in slots if s["role"] == "B"}
        self.assertTrue(b_ids <= {"opec-x0", "opec-x1", "opec-x2"})

    def test_role_c_universe_is_frame_lane_only(self):
        slots = g6c.select_cases(_fx_rows())
        for s in slots:
            if s["role"] == "C":
                self.assertTrue(s["candidate_id"].startswith("fomc-"))

    def test_tie_breaks_by_date_then_id(self):
        rows = [
            _fx_row("opec-late", "designed_contrast", "opec",
                    "2024-05-01", 2.0, None),
            _fx_row("opec-early", "designed_contrast", "opec",
                    "2024-01-01", 2.0, 3.0),
            _fx_row("opec-same-day-b", "designed_contrast", "opec",
                    "2024-01-01", 2.0, 3.1),
            _fx_row("fomc-f", "frame_complete_historical", "fomc",
                    "2024-02-01", 1.0, None),
        ]
        slots = g6c.select_cases(rows)
        a25 = next(s for s in slots if s["role"] == "A"
                   and s["quantile"] == "q25")
        # all three OPEC states equal 2.0 -> distance ties -> earliest
        # date wins; same-day tie -> ascending candidate id.
        self.assertEqual(a25["candidate_id"], "opec-early")

    def test_selection_never_sees_outcomes(self):
        import inspect
        params = inspect.signature(g6c.select_cases).parameters
        self.assertEqual(list(params), ["rows"])
        slots1 = g6c.select_cases(_fx_rows())

        def gate_a(event, benchmark_ticker):
            return _payload(0.01)

        def gate_b(event, benchmark_ticker):
            return _payload(-0.09)

        def _payload(base):
            return {"status": esv.STATUS_AVAILABLE,
                    "auto_adjust_basis": {"asset": True, "benchmark": True},
                    "per_horizon": [
                        {"horizon": h, "raw_return": base,
                         "benchmark_return": 0.0,
                         "abnormal_return": base, "sar": base * 10,
                         "car": 0.0} for h in (1, 5, 20)]}
        r_a = g6a.compute_readouts(_fx_rows(), gate=gate_a)
        r_b = g6a.compute_readouts(_fx_rows(), gate=gate_b)
        ids_a = [s["candidate_id"] for s in slots1]
        self.assertEqual(ids_a,
                         [s["candidate_id"]
                          for s in g6c.select_cases(_fx_rows())])
        self.assertNotEqual(json.dumps(r_a), json.dumps(r_b))
        # readouts play no part: selection identical regardless

    def test_duplicate_role_selection_is_preserved(self):
        rows = [
            _fx_row("opec-only", "designed_contrast", "opec",
                    "2024-01-01", 1.0, 3.0),
            _fx_row("fomc-f1", "frame_complete_historical", "fomc",
                    "2024-02-01", 0.0, None),
            _fx_row("fomc-f2", "frame_complete_historical", "fomc",
                    "2024-03-01", 2.0, None),
        ]
        slots = g6c.select_cases(rows)
        self.assertEqual(len(slots), 6)
        opec_slots = [s for s in slots if s["lane"] == "designed_contrast"]
        self.assertEqual(len(opec_slots), 4)  # A q25/q75 + B q25/q75
        self.assertTrue(all(s["candidate_id"] == "opec-only"
                            for s in opec_slots))
        uniq = g6c.unique_cases(slots)
        entry = next(u for u in uniq if u["candidate_id"] == "opec-only")
        self.assertEqual(len(entry["slots"]), 4)

    def test_selection_is_deterministic(self):
        rows = _fx_rows()
        self.assertEqual(g6c.select_cases(rows),
                         g6c.select_cases(list(reversed(rows))))


class NoteHygieneTests(unittest.TestCase):
    """The manual interpretation notes may carry NO computed research
    number: code supplies every numeric fact at render time. Static
    source facts quoted from the pinned G1 ledger (e.g. '2.2 mb/d',
    '1.75-2.00 percent') are the only permitted digits."""

    _BANNED_PATTERNS = (
        (r"\d+(\.\d+)?\s*%", "outcome percentage"),
        (r"(?i)\bsar\b\s*[-+±(]?\d", "SAR value"),
        (r"(?<![\d.])[-+]0\.\d+", "rho/state-style signed decimal"),
        (r"\d+(\.\d+)?\s*sigma", "sigma magnitude"),
        (r"\b\d+ of (the )?\d+\b", "reversal/fraction count"),
        (r"\b\d+/\d+\b", "count ratio"),
        (r"(?i)rho\s*[-+=0-9]", "rho constant"),
        (r"(?i)\bN\s*=\s*\d", "sample-size constant"),
    )

    _UNSUPPORTED_LANGUAGE = ("election", "heavily previewed",
                             "widely anticipated", "previewed")

    def test_notes_contain_no_computed_numbers(self):
        import re
        from scripts.g6c_representative_cases import CASE_NOTES
        for cid, note in CASE_NOTES.items():
            for field, text in note.items():
                for pattern, label in self._BANNED_PATTERNS:
                    self.assertIsNone(
                        re.search(pattern, text),
                        f"{cid}.{field}: hardcoded {label} matches "
                        f"{pattern!r}")

    def test_notes_contain_no_unsupported_external_context(self):
        from scripts.g6c_representative_cases import CASE_NOTES
        for cid, note in CASE_NOTES.items():
            joined = " ".join(note.values()).lower()
            for phrase in self._UNSUPPORTED_LANGUAGE:
                self.assertNotIn(phrase, joined, f"{cid}: {phrase!r}")

    def test_fomc_hold_case_uses_bounded_wording(self):
        from scripts.g6c_representative_cases import CASE_NOTES
        note = CASE_NOTES["fomc-policy-decision-2018-05-02"]
        joined = " ".join(note.values())
        self.assertNotIn("cannot test transmission at all", joined)
        self.assertIn("cannot isolate decision content from prior "
                      "expectations", joined)


class GeneratedReadoutProseTests(unittest.TestCase):
    """Rendered case numbers must come from the supplied readout data."""

    @staticmethod
    def _metrics(base):
        return {m: {1: base + 0.001, 5: base + 0.005, 20: base + 0.020}
                for m in g6a.METRICS}

    def test_prose_carries_numbers_from_supplied_data(self):
        text = g6c.render_case_readout(self._metrics(0.03))
        self.assertIn("+3.10%", text)   # absolute 1d = 0.031
        self.assertIn("+3.50%", text)   # 5d
        self.assertIn("+5.00%", text)   # 20d
        for label in ("Absolute asset return", "Against SPY",
                      "sector benchmark", "SAR"):
            self.assertIn(label, text)

    def test_perturbed_readout_changes_rendered_prose(self):
        a = g6c.render_case_readout(self._metrics(0.03))
        b = g6c.render_case_readout(self._metrics(-0.08))
        self.assertNotEqual(a, b)
        self.assertIn("-7.90%", b)

    def test_prose_reports_all_three_horizons_and_peak_sar(self):
        m = self._metrics(0.0)
        m["sar"] = {1: 0.4, 5: -1.7, 20: 0.2}
        text = g6c.render_case_readout(m)
        self.assertIn("largest standardized move is -1.70 at 5d", text)


@unittest.skipUnless(LIVE_READY, "ledgers, promoted rows, cache required")
class ProhibitedFramingTests(unittest.TestCase):
    def test_tracked_report_has_no_prohibited_framing(self):
        artifact = ROOT / "stats" / "G6C_REPRESENTATIVE_CASES.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        import re
        text = artifact.read_text(encoding="utf-8").lower()
        for banned in ("strongest-looking", "winner", "best result",
                       "strongest signal", "validated relationship",
                       "trade recommendation"):
            self.assertNotIn(banned, text, banned)
        # word-boundary check: 'selection' must not trip this ban
        self.assertIsNone(re.search(r"\belection\b", text))
        # 'causal fed effect' may appear ONLY as an explicit rejection.
        for line in text.splitlines():
            if "causal fed effect" in line:
                self.assertIn("rejected", line, line[:120])

    def test_report_prose_agrees_with_underlying_readout(self):
        rows = g6a.load_promoted_rows()
        readouts = g6a.compute_readouts(rows)
        text = (ROOT / "stats" / "G6C_REPRESENTATIVE_CASES.md"
                ).read_text(encoding="utf-8")
        slots = g6c.select_cases(rows)
        for cid in {s["candidate_id"] for s in slots}:
            expected = g6c.render_case_readout(readouts[cid]["metrics"])
            self.assertIn(expected, text, cid)


@unittest.skipUnless(LIVE_READY, "ledgers, promoted rows, cache required")
class FrozenSelectionRegressionTests(unittest.TestCase):
    """The six selected ids are frozen; this correction slice (and any
    future edit) must not move them."""

    FROZEN = (
        ("A", "q25", "opec-2024-11-03-one-month-delay"),
        ("A", "q75", "opec-2023-11-30-voluntary-2p2"),
        ("B", "q25", "opec-2025-09-07-oct-137k"),
        ("B", "q75", "opec-2024-03-03-q2-extension"),
        ("C", "q25", "fomc-policy-decision-2019-09-18"),
        ("C", "q75", "fomc-policy-decision-2018-05-02"),
    )

    def test_selected_ids_are_exactly_the_frozen_six(self):
        slots = g6c.select_cases(g6a.load_promoted_rows())
        got = tuple((s["role"], s["quantile"], s["candidate_id"])
                    for s in slots)
        self.assertEqual(got, self.FROZEN)


@unittest.skipUnless(LIVE_READY, "ledgers, promoted rows, cache required")
class LiveSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = g6a.load_promoted_rows()
        cls.slots = g6c.select_cases(cls.rows)

    def test_live_universes_have_frozen_denominators(self):
        u = {r["role"]: len(g6c.role_universe(self.rows, r))
             for r in g6c.ROLES}
        self.assertEqual(u, {"A": 32, "B": 16, "C": 65})

    def test_live_six_slots_within_correct_universes(self):
        self.assertEqual(len(self.slots), 6)
        for s in self.slots:
            if s["role"] in ("A", "B"):
                self.assertTrue(s["candidate_id"].startswith("opec-"))
            else:
                self.assertTrue(s["candidate_id"].startswith("fomc-"))

    def test_ledger_provenance_exists_for_every_selected_case(self):
        info = g6c.load_case_info()
        for s in self.slots:
            entry = info[s["candidate_id"]]
            self.assertTrue(entry["source_ref"].strip())
            self.assertTrue(entry["description"].strip())

    def test_report_regenerates_byte_identically(self):
        artifact = ROOT / "stats" / "G6C_REPRESENTATIVE_CASES.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         g6c.build_report_text())

    def test_report_carries_contract_and_rejected_interpretations(self):
        text = g6c.build_report_text()
        for required in (
                "outcome magnitude was not used",
                "post-readout",
                "## Rejected interpretations",
                "stable descriptive association with unresolved "
                "calendar-time confounding",
                "illustrations, never proof"):
            self.assertIn(required, text)
        for banned in ("strongest signal", "best trade", "alpha",
                       "winner"):
            self.assertNotIn(banned, text.lower())


if __name__ == "__main__":
    unittest.main()
