"""Tests for scripts/track_record_sensitivity_report.py (read-only).

Covers canonical source-selection (revisit-preferred with the dir_cnt>0 gate)
and the accepted-track-record denominator (NON_THESIS_STAGES + synthetic_seed
excluded), with all rules sharing one denominator.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import track_record_sensitivity_report as R  # noqa: E402


def _sup(sym="A"):
    return {"symbol": sym, "direction_tag": "supports up"}


def _con(sym="B"):
    return {"symbol": sym, "direction_tag": "contradicts down"}


class TestSourceSelection(unittest.TestCase):
    def test_revisit_with_directional_tags_is_used(self):
        revisit = json.dumps([{"day": 20, "tickers": [{"symbol": "X", "direction": "supports up"}]}])
        market = json.dumps([_con("X")])
        picked = R._select_source_tickers(market, revisit)
        # The revisit snapshot (supporting) wins over market_tickers (contradicting).
        self.assertEqual(picked[0].get("direction"), "supports up")

    def test_revisit_without_direction_falls_back_to_market(self):
        revisit = json.dumps([{"day": 20, "tickers": [{"symbol": "X"}]}])  # no tag
        market = json.dumps([_sup("X")])
        picked = R._select_source_tickers(market, revisit)
        self.assertEqual(picked[0].get("direction_tag"), "supports up")

    def test_no_revisit_uses_market(self):
        picked = R._select_source_tickers(json.dumps([_sup("X")]), None)
        self.assertEqual(picked[0].get("direction_tag"), "supports up")


class TestBuildReport(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(tempfile.gettempdir(), f"trsr_{uuid.uuid4().hex}.db")
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(
                "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, "
                "mechanism_family TEXT, market_tickers TEXT, revisit_snapshots TEXT, stage TEXT)"
            )
            conn.execute(
                "CREATE TABLE event_hygiene (event_id INTEGER PRIMARY KEY, "
                "override_class TEXT, override_reason TEXT, created_at TEXT)"
            )

            def ev(i, mt, stage="realized", revisit=None, fam="tariff"):
                conn.execute(
                    "INSERT INTO events (id, headline, mechanism_family, market_tickers, "
                    "revisit_snapshots, stage) VALUES (?,?,?,?,?,?)",
                    (i, f"h{i}", fam, json.dumps(mt), revisit, stage),
                )

            ev(1, [_sup(), _con(), _con(), _con()])          # any=val, maj=con
            ev(2, [_sup(), _sup()])                          # all rules val
            ev(3, [{"symbol": "Z"}])                         # no direction -> unresolved
            ev(4, [_sup()], stage="curated_observation")     # NON_THESIS -> excluded
            ev(5, [_sup()], stage="realized")                # flagged synthetic -> excluded
            # e6: revisit supports overrides market contradicts
            ev(6, [_con()], revisit=json.dumps(
                [{"day": 20, "tickers": [{"symbol": "X", "direction": "supports up"}]}]))
            conn.execute(
                "INSERT INTO event_hygiene VALUES (5, 'synthetic_seed', 'test', '2026-06-10')"
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_denominator_excludes_non_thesis_and_synthetic(self):
        rep = R.build_report(db_path=self._tmp, limit=50)
        denom = rep["denominator"]
        self.assertEqual(denom["accepted_track_record_events"], 4)  # e1,e2,e3,e6
        self.assertEqual(denom["archive_rows"], 6)
        self.assertEqual(denom["synthetic_seed_excluded"], 1)       # e5
        self.assertGreaterEqual(denom["non_thesis_stage_excluded"], 1)  # e4

    def test_any_support_split_matches_hand_count(self):
        rep = R.build_report(db_path=self._tmp, limit=50)
        a = rep["scoring"]["rules"]["any_support"]
        # e1 val, e2 val, e3 unresolved, e6 val (via revisit)
        self.assertEqual((a["validated"], a["contradicted"], a["unresolved"]), (3, 0, 1))

    def test_majority_flips_e1_and_shares_denominator(self):
        rep = R.build_report(db_path=self._tmp, limit=50)
        sc = rep["scoring"]
        self.assertEqual(sc["denominator"], 4)
        for rule in R.RULES:
            r = sc["rules"][rule]
            self.assertEqual(r["validated"] + r["contradicted"] + r["unresolved"], 4)
        m = sc["rules"]["majority"]
        # e1 flips val->con; e2 val; e3 unresolved; e6 val
        self.assertEqual((m["validated"], m["contradicted"], m["unresolved"]), (2, 1, 1))

    def test_text_render_is_ascii_safe(self):
        rep = R.build_report(db_path=self._tmp, limit=50)
        text = R._render_text(rep)
        text.encode("cp1252")  # must not raise on a Windows console codepage
        self.assertIn("scoring-rule sensitivity", text.lower())


if __name__ == "__main__":
    unittest.main()
