"""Tests for scripts/track_record_horizon_sensitivity_report.py (read-only).

H1 — horizon-sensitivity diagnostics for the accepted track-record outcomes.
Covers: canonical best-available reproduction on fixtures, the 20d > 5d > 1d
selection priority being MEASURED (never changed), per-horizon denominator
identities, flip detection vs canonical and across horizons, missing-horizon
surfacing, no-mutation, no-provider, and banned-framing guards. The canonical
headline stays separate from the horizon diagnostics.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import db  # noqa: E402
from scripts import track_record_horizon_sensitivity_report as H  # noqa: E402


def _sup(sym="A"):
    return {"symbol": sym, "direction": "supports up"}


def _con(sym="B"):
    return {"symbol": sym, "direction": "contradicts down"}


def _mk_sup(sym="A"):
    return {"symbol": sym, "direction_tag": "supports up"}


def _snap(day, tickers):
    return {"day": day, "tickers": tickers}


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestBestSnapshotAdapter(unittest.TestCase):
    """The (day, tickers) adapter must match db._best_revisit_snapshot exactly."""

    CASES = (
        [],
        [_snap(20, [])],
        [_snap(1, [_sup()])],
        [_snap(1, [_sup()]), _snap(5, [_con()]), _snap(20, [_sup("C")])],
        [_snap(20, []), _snap(5, [_con()])],          # 20d empty -> 5d wins
        [_snap(5, [{"symbol": "Z"}]), _snap(1, [_sup()])],  # tagless still "has tickers"
    )

    def test_tickers_identical_to_canonical_helper(self):
        for snaps in self.CASES:
            day, tickers = H._best_snapshot_with_day(snaps)
            canonical = db._best_revisit_snapshot(list(snaps))
            self.assertEqual(tickers, canonical, msg=f"snaps={snaps!r}")
            if canonical is None:
                self.assertIsNone(day)

    def test_day_reported_for_winning_snapshot(self):
        day, _ = H._best_snapshot_with_day(
            [_snap(1, [_sup()]), _snap(20, [_con()])])
        self.assertEqual(day, 20)
        day, _ = H._best_snapshot_with_day([_snap(20, []), _snap(5, [_con()])])
        self.assertEqual(day, 5)


class TestBuildReport(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"trhs_{uuid.uuid4().hex}.db")
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(
                "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, "
                "mechanism_family TEXT, market_tickers TEXT, "
                "revisit_snapshots TEXT, stage TEXT)"
            )
            conn.execute(
                "CREATE TABLE event_hygiene (event_id INTEGER PRIMARY KEY, "
                "override_class TEXT, override_reason TEXT, created_at TEXT)"
            )

            def ev(i, mt, stage="realized", revisit=None):
                conn.execute(
                    "INSERT INTO events (id, headline, mechanism_family, "
                    "market_tickers, revisit_snapshots, stage) "
                    "VALUES (?,?,?,?,?,?)",
                    (i, f"h{i}", "tariff", json.dumps(mt), revisit, stage),
                )

            # e1: 1d support, 5d support, 20d contradiction
            #   -> canonical uses 20d (contradiction); flips across horizons.
            ev(1, [_mk_sup()], revisit=json.dumps(
                [_snap(1, [_sup()]), _snap(5, [_sup()]), _snap(20, [_con()])]))
            # e2: market_tickers support only, no revisit -> canonical fallback.
            ev(2, [_mk_sup()])
            # e3: 5d contradiction only -> canonical uses 5d.
            ev(3, [_mk_sup()], revisit=json.dumps([_snap(5, [_con()])]))
            # e4: 20d snapshot has tickers but NO direction tags; market
            #     supports -> canonical dir_cnt>0 gate falls back to market.
            ev(4, [_mk_sup()], revisit=json.dumps(
                [_snap(20, [{"symbol": "Z"}])]))
            # e5: NON_THESIS stage -> excluded from denominator.
            ev(5, [_mk_sup()], stage="curated_observation")
            # e6: synthetic_seed flagged -> excluded.
            ev(6, [_mk_sup()])
            # e7: 1d support only -> canonical uses 1d.
            ev(7, [_mk_sup()], revisit=json.dumps([_snap(1, [_sup()])]))
            conn.execute(
                "INSERT INTO event_hygiene VALUES "
                "(6, 'synthetic_seed', 'test', '2026-06-11')"
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _report(self):
        return H.build_report(db_path=self._tmp, limit=5)

    # --- denominator -----------------------------------------------------

    def test_denominator_excludes_non_thesis_and_synthetic(self):
        denom = self._report()["denominator"]
        self.assertEqual(denom["accepted_track_record_events"], 5)  # 1,2,3,4,7
        self.assertEqual(denom["archive_rows"], 7)
        self.assertEqual(denom["synthetic_seed_excluded"], 1)
        self.assertGreaterEqual(denom["non_thesis_stage_excluded"], 1)

    # --- canonical reproduction -------------------------------------------

    def test_canonical_reproduces_expected_labels(self):
        canon = self._report()["canonical"]
        # e1 contradiction (20d), e2 support (fallback), e3 contradiction (5d),
        # e4 support (fallback via dir_cnt>0 gate), e7 support (1d).
        self.assertEqual(canon["validated"], 3)
        self.assertEqual(canon["contradicted"], 2)
        self.assertEqual(canon["unresolved"], 0)
        self.assertEqual(canon["total"], 5)

    def test_canonical_horizon_distribution(self):
        dist = self._report()["canonical"]["horizon_distribution"]
        self.assertEqual(dist["snapshot_20d"], 1)   # e1
        self.assertEqual(dist["snapshot_5d"], 1)    # e3
        self.assertEqual(dist["snapshot_1d"], 1)    # e7
        self.assertEqual(dist["market_tickers_fallback"], 2)  # e2, e4
        total = self._report()["canonical"]["total"]
        self.assertEqual(
            dist["snapshot_20d"] + dist["snapshot_5d"] + dist["snapshot_1d"]
            + dist["market_tickers_fallback"]
            + dist.get("snapshot_other_day", 0),
            total,
        )

    def test_priority_measured_not_changed(self):
        """20d wins for e1 even though 1d/5d disagree; e4's tagless 20d
        snapshot still falls back to market_tickers (dir_cnt>0 gate)."""
        rep = self._report()
        per_event = {e["event_id"]: e for e in rep["per_event"]}
        self.assertEqual(per_event[1]["canonical_outcome"], "contradiction")
        self.assertEqual(per_event[1]["canonical_source"], "snapshot_20d")
        self.assertEqual(per_event[4]["canonical_outcome"], "support")
        self.assertEqual(per_event[4]["canonical_source"],
                         "market_tickers_fallback")

    # --- per-horizon blocks ------------------------------------------------

    def test_per_horizon_counts_sum_to_denominators(self):
        rep = self._report()
        total = rep["canonical"]["total"]
        for key in ("1d", "5d", "20d"):
            block = rep["horizons"][key]
            self.assertEqual(
                block["support"] + block["contradiction"]
                + block["unresolved"],
                block["available"], msg=key)
            self.assertEqual(block["available"] + block["missing"], total,
                             msg=key)
            self.assertLessEqual(block["data_limited_no_direction"],
                                 block["unresolved"], msg=key)

    def test_missing_horizons_surfaced_not_dropped(self):
        rep = self._report()
        # 1d available: e1, e7 -> missing 3.  5d: e1, e3 -> missing 3.
        # 20d: e1, e4 -> missing 3.
        self.assertEqual(rep["horizons"]["1d"]["missing"], 3)
        self.assertEqual(rep["horizons"]["5d"]["missing"], 3)
        self.assertEqual(rep["horizons"]["20d"]["missing"], 3)

    def test_data_limited_counted_at_20d(self):
        block = self._report()["horizons"]["20d"]
        # e4's 20d snapshot has a ticker but no direction tag.
        self.assertEqual(block["data_limited_no_direction"], 1)
        self.assertEqual(block["unresolved"], 1)

    # --- flips ---------------------------------------------------------------

    def test_flip_vs_canonical_detected(self):
        rep = self._report()
        h1 = rep["horizons"]["1d"]
        # e1: canonical contradiction, 1d support.
        self.assertEqual(h1["differs_from_canonical"], 1)
        self.assertEqual(
            h1["flip_matrix_vs_canonical"]["contradiction_to_support"], 1)
        h20 = rep["horizons"]["20d"]
        # e4: canonical support, 20d unresolved.
        self.assertEqual(h20["differs_from_canonical"], 1)
        self.assertEqual(
            h20["flip_matrix_vs_canonical"]["support_to_unresolved"], 1)
        # e1 agrees with canonical at 20d -> not counted there.
        self.assertEqual(
            h20["flip_matrix_vs_canonical"]["contradiction_to_support"], 0)

    def test_examples_are_deterministic_and_capped(self):
        h1 = self._report()["horizons"]["1d"]
        ex = h1["examples_differs"]
        self.assertLessEqual(len(ex), 5)
        self.assertEqual(ex[0]["event_id"], 1)
        self.assertEqual(ex[0]["canonical"], "contradiction")
        self.assertEqual(ex[0]["horizon_outcome"], "support")

    def test_cross_horizon_flip_detected(self):
        cross = self._report()["cross_horizon"]
        # Only e1 has 2+ horizons available; its outcomes disagree.
        self.assertEqual(cross["events_with_2plus_horizons"], 1)
        self.assertEqual(cross["events_flipping_between_horizons"], 1)
        self.assertEqual(cross["examples"][0]["event_id"], 1)

    # --- safety / honesty guards --------------------------------------------

    def test_report_does_not_mutate_db(self):
        before = _sha256(self._tmp)
        self._report()
        self.assertEqual(_sha256(self._tmp), before)

    def test_no_provider_or_network_imports_in_script(self):
        src_path = os.path.join(
            _REPO, "scripts", "track_record_horizon_sensitivity_report.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            src = fh.read()
        for token in ("requests", "urllib", "httpx", "yfinance", "socket",
                      "aiohttp", "/analyze"):
            self.assertNotIn(token, src, msg=token)

    def test_no_banned_framing_in_output(self):
        rep = self._report()
        text = H._render_text(rep) + "\n" + json.dumps(rep, default=str)
        low = text.lower()
        for phrase in ("statistically significant", "trading signal",
                       "validated-as-success", "recommendation", "forecast"):
            self.assertNotIn(phrase, low, msg=phrase)
        for word in ("proof", "alpha", "buy", "sell"):
            self.assertIsNone(
                re.search(rf"\b{word}\b", low), msg=word)

    def test_canonical_headline_separate_from_diagnostics(self):
        rep = self._report()
        self.assertIn("canonical", rep)
        self.assertIn("horizons", rep)
        # Horizon diagnostic blocks never reuse the canonical headline keys.
        for key in ("1d", "5d", "20d"):
            self.assertNotIn("validated", rep["horizons"][key])
            self.assertNotIn("contradicted", rep["horizons"][key])
        # And an interpretation note declares the diagnostics non-canonical.
        joined = " ".join(rep["interpretation_note"]).lower()
        self.assertIn("canonical", joined)
        self.assertIn("diagnostic", joined)

    def test_text_render_cp1252_safe(self):
        text = H._render_text(self._report())
        text.encode("cp1252")  # must not raise on a Windows console codepage
        self.assertIn("horizon", text.lower())


if __name__ == "__main__":
    unittest.main()
