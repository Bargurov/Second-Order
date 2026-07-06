"""Tests for I2A - the deterministic symmetric response substrate.

Contract under test (I0 protocol i0-v1; task I2A):

* ONE response-computation path serves both memberships: an event date and
  an ordinary reference date with the same family, horizon, anchor, and
  price availability produce IDENTICAL basis choice and metric values
  (raw return, SPY-relative AR, sector-relative AR, SAR) - only
  membership/identity metadata differs; failures are identical too;
* the frozen basis policy holds per record (adjusted/adjusted preferred,
  matched raw/raw disclosed fallback, cross-basis fails closed);
* extraction is deterministic and uncurated (fixed family/membership/
  identity/horizon/metric order; no magnitude sorting or filtering);
* denominators reconcile exactly: FOMC 65 / OPEC 32 event identities,
  reference attempts equal to the I1 manifests (1816/1299; 1903/1631/889),
  the OPEC register never leaks into event membership;
* every attempted record carries a status; no record carries any
  percentile/MEMP/calibration/interpretation field;
* the tracked report is coverage-and-integrity only.

Fixtures use a temp price DB via the G3 builder; live tests skip without
the local price cache.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts import i2a_response_substrate as i2a  # noqa: E402
from scripts.g3_mechanical_grinder import build_price_db  # noqa: E402

LIVE_DB = i1.default_db_path()
LIVE_READY = LIVE_DB.exists()


# ---------------------------------------------------------------------------
# Fixture: a tiny three-ticker family with deterministic prices, both bases
# ---------------------------------------------------------------------------


def _sessions(n: int, start=(2024, 1, 2)) -> list[str]:
    out, cur = [], date(*start)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


SESSIONS = _sessions(90)


def _series(base: float, drift: float) -> dict[str, float]:
    return {d: base + drift * i + (0.5 if i % 7 == 0 else 0.0)
            for i, d in enumerate(SESSIONS)}


def _fixture_db(dirname: str, *, cross_basis: bool = False,
                raw_only: bool = False) -> Path:
    path = Path(dirname) / "i2a_fixture_prices.db"
    aaa_raw, aaa_adj = _series(100, 0.3), _series(98, 0.3)
    bbb_raw, bbb_adj = _series(400, 0.5), _series(395, 0.5)
    ccc_raw, ccc_adj = _series(50, 0.1), _series(49, 0.1)
    if raw_only:
        aaa_adj, bbb_adj, ccc_adj = {}, {}, {}
    if cross_basis:
        aaa_raw = {}   # primary adjusted-only
        bbb_adj = {}   # benchmark raw-only -> no matched pair
    build_price_db(path, {
        "AAA": (aaa_raw, aaa_adj),
        "BBB": (bbb_raw, bbb_adj),
        "CCC": (ccc_raw, ccc_adj),
    }, fetched_at="2026-01-01T00:00:00+00:00")
    return path


FIX_LANE = i2a.LaneAssets(family="FIX", primary="AAA", benchmark="BBB",
                          sector="CCC")
# Per-horizon readiness (I2A-1): each requested horizon is judged on its own
# forward window (>= 60 prior sessions AND forward cache through that horizon),
# symmetric across memberships. GOOD_ANCHOR clears every shipped horizon.
GOOD_ANCHOR = SESSIONS[65]      # 65 prior, 24 forward (clears 1d/5d/20d)
EARLY_ANCHOR = SESSIONS[10]     # insufficient estimation window


def _compute(db, membership, identity, anchor, horizons=(1, 5)):
    return i2a.compute_membership_records(
        FIX_LANE, membership,
        [i2a.AttemptItem(identity=identity, source_date=anchor,
                         anchor_session=anchor, horizons=tuple(horizons))],
        db_path=db)


class SymmetryTests(unittest.TestCase):
    def test_same_anchor_same_response_only_metadata_differs(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            ev = _compute(db, "event", "fix-event-1", GOOD_ANCHOR)
            ref = _compute(db, "reference", GOOD_ANCHOR, GOOD_ANCHOR)
        self.assertEqual(len(ev), len(ref))
        self.assertEqual(len(ev), 2 * len(i2a.METRICS))
        for e, r in zip(ev, ref):
            self.assertEqual(e["status"], "available")
            for field in ("family", "horizon", "metric", "value", "basis",
                          "primary_ticker", "benchmark_used", "status",
                          "failure_reason", "anchor_session"):
                self.assertEqual(e[field], r[field], field)
            self.assertEqual(e["membership"], "event")
            self.assertEqual(r["membership"], "reference")
            self.assertNotEqual(e["identity"], r["identity"])

    def test_same_failure_same_failure(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            ev = _compute(db, "event", "fix-event-2", EARLY_ANCHOR)
            ref = _compute(db, "reference", EARLY_ANCHOR, EARLY_ANCHOR)
        for e, r in zip(ev, ref):
            self.assertEqual(e["status"], "unavailable")
            self.assertEqual(r["status"], "unavailable")
            self.assertEqual(e["failure_reason"], r["failure_reason"])
            self.assertIn("insufficient_estimation", e["failure_reason"])
            self.assertIsNone(e["value"])


class BasisPolicyTests(unittest.TestCase):
    def test_adjusted_adjusted_is_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            recs = _compute(db, "reference", GOOD_ANCHOR, GOOD_ANCHOR)
        self.assertTrue(all(r["basis"] == "adjusted" for r in recs))

    def test_matched_raw_raw_fallback_is_disclosed(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td, raw_only=True)
            recs = _compute(db, "reference", GOOD_ANCHOR, GOOD_ANCHOR)
        self.assertTrue(all(r["status"] == "available" for r in recs))
        self.assertTrue(all(r["basis"] == "raw_fallback" for r in recs))

    def test_cross_basis_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td, cross_basis=True)
            recs = _compute(db, "event", "fix-event-3", GOOD_ANCHOR)
        # canonical pair (AAA/BBB) has no matched basis -> raw/spy/sar
        # records must be unavailable, never a mixed pair.
        canonical = [r for r in recs
                     if r["metric"] != "sector_relative_ar"]
        self.assertTrue(all(r["status"] == "unavailable"
                            for r in canonical))
        self.assertTrue(all(r["basis"] is None for r in canonical))


class DeterminismAndHygieneTests(unittest.TestCase):
    def test_repeated_extraction_is_identical(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            a = _compute(db, "event", "fix-event-4", GOOD_ANCHOR)
            b = _compute(db, "event", "fix-event-4", GOOD_ANCHOR)
        self.assertEqual(a, b)

    def test_records_carry_no_comparison_fields(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            recs = _compute(db, "event", "fix-event-5", GOOD_ANCHOR)
        dumped = json.dumps(recs).lower()
        for banned in ("percentile", "memp", "calibration", "unusual",
                       "rank", "winner", "significan", "p_value"):
            self.assertNotIn(banned, dumped, banned)
        for r in recs:
            self.assertEqual(set(r), set(i2a.RECORD_FIELDS))
            self.assertEqual(r["contract_version"], i2a.SUBSTRATE_VERSION)

    def test_missing_price_db_fails_loudly(self):
        with self.assertRaises(Exception):
            _compute(Path("Z:/nonexistent/prices.db"), "event",
                     "fix-event-6", GOOD_ANCHOR)


# Short-tail anchor: >= 60 prior sessions but only 9 forward, so the 1d and
# 5d response windows are computable while the 20d window is not. Per-horizon
# readiness must judge each requested horizon on its OWN forward window, never
# on the maximum shipped horizon.
SHORT_TAIL_ANCHOR = SESSIONS[80]


class PerHorizonReadinessTests(unittest.TestCase):
    @staticmethod
    def _statuses_by_horizon(recs):
        by_h: dict[int, set] = {}
        for r in recs:
            by_h.setdefault(r["horizon"], set()).add(r["status"])
        return by_h

    def test_shorter_horizons_available_without_20d_tail(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            recs = _compute(db, "reference", SHORT_TAIL_ANCHOR,
                            SHORT_TAIL_ANCHOR, horizons=(1, 5, 20))
        by_h = self._statuses_by_horizon(recs)
        self.assertEqual(by_h[1], {"available"},
                         "1d must not depend on 20d availability")
        self.assertEqual(by_h[5], {"available"},
                         "5d must not depend on 20d availability")
        self.assertEqual(by_h[20], {"unavailable"},
                         "20d must be unavailable when its own tail is absent")

    def test_20d_unavailable_names_its_own_forward_window(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            recs = _compute(db, "reference", SHORT_TAIL_ANCHOR,
                            SHORT_TAIL_ANCHOR, horizons=(1, 5, 20))
        for r in recs:
            if r["horizon"] == 20:
                self.assertEqual(r["status"], "unavailable")
                self.assertIn("20d", r["failure_reason"] or "",
                              "20d must fail for its own explicit reason")
                self.assertIsNone(r["value"])
            else:
                # shorter horizons available with a real value, never a silent
                # substitution of a longer/shorter horizon's number
                self.assertEqual(r["status"], "available")
                self.assertIsNotNone(r["value"])

    def test_short_tail_symmetry_event_equals_reference(self):
        with tempfile.TemporaryDirectory() as td:
            db = _fixture_db(td)
            ev = _compute(db, "event", "fix-st-ev", SHORT_TAIL_ANCHOR,
                          horizons=(1, 5, 20))
            ref = _compute(db, "reference", SHORT_TAIL_ANCHOR,
                           SHORT_TAIL_ANCHOR, horizons=(1, 5, 20))
        self.assertEqual(len(ev), len(ref))
        for e, r in zip(ev, ref):
            for field in ("family", "horizon", "metric", "value", "basis",
                          "status", "failure_reason"):
                self.assertEqual(e[field], r[field], field)


@unittest.skipUnless(LIVE_READY, "local G3 price cache required")
class LiveSubstrateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sub = i2a.build_substrate()

    def test_event_identities_reconcile_exactly(self):
        rec = self.sub["reconciliation"]
        self.assertEqual(rec["FOMC"]["event_identities"], 65)
        self.assertEqual(rec["OPEC"]["event_identities"], 32)

    def test_reference_attempts_reconcile_to_i1_manifests(self):
        rec = self.sub["reconciliation"]
        self.assertEqual(rec["FOMC"]["reference_attempts"],
                         {1: 1816, 5: 1299})
        self.assertEqual(rec["OPEC"]["reference_attempts"],
                         {1: 1903, 5: 1631, 20: 889})

    def test_fomc_20d_has_no_primary_substrate(self):
        self.assertFalse(any(
            r["family"] == "FOMC" and r["horizon"] == 20
            for r in self.sub["records"]))

    def test_register_never_leaks_into_event_membership(self):
        self.assertEqual(
            self.sub["reconciliation"]["OPEC"]["register_event_overlap"], 0)
        opec_event_ids = {r["identity"] for r in self.sub["records"]
                          if r["family"] == "OPEC"
                          and r["membership"] == "event"}
        self.assertEqual(len(opec_event_ids), 32)

    def test_every_attempted_record_has_a_status(self):
        self.assertTrue(all(r["status"] in ("available", "unavailable")
                            for r in self.sub["records"]))
        self.assertTrue(all(
            r["failure_reason"] is not None
            for r in self.sub["records"] if r["status"] == "unavailable"))

    def test_deterministic_uncurated_ordering(self):
        keys = [(r["family"], r["membership"], r["identity"], r["horizon"],
                 i2a.METRICS.index(r["metric"]))
                for r in self.sub["records"]]
        self.assertEqual(keys, sorted(keys))

    def test_report_is_coverage_only(self):
        text = i2a.render_report(self.sub)
        low = text.lower()
        for banned in ("memp", "percentile", "calibration", "unusual",
                       "strongest", "winner", "significan", "versus the",
                       "p-value"):
            self.assertNotIn(banned, low, banned)
        self.assertIn("basis", low)
        self.assertIn("coverage", low)

    def test_tracked_report_matches_regeneration(self):
        artifact = ROOT / "stats" / "I2A_RESPONSE_SUBSTRATE.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         i2a.render_report(self.sub))


if __name__ == "__main__":
    unittest.main()
