"""Tests for scripts/uaw_supplier_transmission_packet.py (read-only).

The UAW transmission packet deepens one staged case (313): direct OEM legs
(GM/F) vs the supplier channel (LEA/APTV), with C4 anchor labels consumed as
input, per-ticker local data flags computed honestly (including the
pre-event-window gap), and no promotion / no paid implication anywhere.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import uaw_supplier_transmission_packet as P  # noqa: E402


_EVENTS_DDL = """
CREATE TABLE events (
    id               INTEGER PRIMARY KEY,
    event_date       TEXT,
    stage            TEXT,
    mechanism_family TEXT,
    headline         TEXT,
    market_tickers   TEXT
)
""".strip()

_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()

_EVENT_HYGIENE_DDL = """
CREATE TABLE event_hygiene (
    event_id        INTEGER PRIMARY KEY,
    override_class  TEXT,
    override_reason TEXT,
    created_at      TEXT
)
""".strip()

_UAW_HEADLINE = "UAW Stand Up Strike begins against GM, Ford, and Stellantis"


def _mt(*symbols):
    return json.dumps([{"symbol": s, "role": "exposed"} for s in symbols])


def _bdays_around(anchor: date, n_pre: int, n_post: int) -> list[date]:
    pre: list[date] = []
    cur = anchor
    while len(pre) < n_pre:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            pre.append(cur)
    pre.reverse()
    post: list[date] = []
    cur = anchor
    while len(post) < n_post:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            post.append(cur)
    return pre + [anchor] + post


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_uaw_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _seed_313(self, *, stage="z1a_candidate_pack", headline=_UAW_HEADLINE):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (313, '2023-09-15', ?, "
                "'labor_inflation', ?, ?)",
                (stage, headline, _mt("GM", "F")),
            )
            conn.commit()

    def _seed_price_row(self, ticker, day="2023-09-15"):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,0,'t')",
                (ticker, day, 100.0, 1.0e6),
            )
            conn.commit()

    def _seed_series(self, ticker, dates, base=100.0, noise=True, jump_from=None):
        with sqlite3.connect(self._tmp) as conn:
            for i, d in enumerate(dates):
                val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
                if jump_from is not None and i >= jump_from:
                    val *= 0.97
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,0,'t')",
                    (ticker, d.isoformat(), val, 1.0e6),
                )
            conn.commit()


class TestPacketBasics(_Base):
    def test_selects_313_staged_no_paid_with_c4_label(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "ok")
        c = pkt["candidate"]
        self.assertEqual(c["event_id"], 313)
        self.assertTrue(c["staged_no_paid"])
        self.assertEqual(c["event_date_quality"], "partial_anticipation")
        self.assertTrue(c["horizon_interpretation_caution"])

    def test_blocked_if_not_staged(self):
        self._seed_313(stage="realized")
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "blocked_candidate_not_staged")
        self.assertFalse(pkt["candidate"]["staged_no_paid"])

    def test_missing_candidate(self):
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "candidate_not_found")

    def test_c4_label_is_derived_not_hardcoded(self):
        self._seed_313(headline="UAW files unfair labor practice charges "
                                "against GM and Ford")
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(pkt["candidate"]["event_date_quality"],
                         "clean_discrete_anchor")


class TestAssetGroups(_Base):
    def test_direct_and_supplier_legs_separated(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        groups = pkt["asset_groups"]
        direct = {e["ticker"] for e in groups["direct_oem_exposures"]}
        supplier = {e["ticker"] for e in groups["supplier_exposures"]}
        self.assertEqual(direct, {"GM", "F"})
        self.assertEqual(supplier, {"LEA", "APTV"})
        self.assertFalse(direct & supplier)

    def test_excluded_assets_disclosed_not_silently_added(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        excluded = {e["ticker"] for e in pkt["asset_groups"]["excluded_assets"]}
        self.assertIn("STLA", excluded)
        self.assertIn("BWA", excluded)

    def test_local_price_data_flags_explicit(self):
        self._seed_313()
        self._seed_price_row("GM")
        pkt = P.build_packet(db_path=self._tmp)
        flags = pkt["local_price_data_flags"]
        self.assertIs(flags["GM"], True)
        self.assertIs(flags["LEA"], False)
        for v in flags.values():
            self.assertIsInstance(v, bool)


class TestReadoutsAndComparison(_Base):
    def test_readouts_carry_n1_descriptive_and_gap_fields(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        for ticker, ro in pkt["local_readouts"].items():
            self.assertTrue(ro["descriptive_only"], ticker)
            self.assertTrue(ro["n_equals_one"], ticker)
            self.assertIn("status", ro)
            self.assertIn("pre_event_distinct_dates", ro)
            self.assertEqual(ro["benchmark_basis"], "SPY")
        self.assertNotEqual(pkt["local_readouts"]["LEA"]["status"],
                            "event_study_available")

    def test_compute_ready_gm_readout_available(self):
        self._seed_313()
        dates = _bdays_around(date(2023, 9, 15), 65, 22)
        self._seed_series("GM", dates, base=33.0, noise=True, jump_from=66)
        self._seed_series("SPY", dates, base=440.0, noise=False)
        pkt = P.build_packet(db_path=self._tmp)
        ro = pkt["local_readouts"]["GM"]
        self.assertEqual(ro["status"], "event_study_available")
        self.assertEqual(len(ro["horizons"]), 3)

    def test_comparison_block_present_with_supplier_gap(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        cmp_ = pkt["comparison"]
        for key in ("direct_oem_pattern", "supplier_pattern",
                    "supplier_vs_oem_summary",
                    "delayed_or_buffered_channel_note",
                    "what_can_be_read", "what_cannot_be_read"):
            self.assertIn(key, cmp_)
            self.assertTrue(cmp_[key])

    def test_mechanism_chain_keys(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        mc = pkt["mechanism_chain"]
        for key in ("strike_start", "production_disruption",
                    "inventory_buffer", "supplier_order_flow",
                    "wage_cost_settlement",
                    "margin_pressure_or_revenue_delay"):
            self.assertIn(key, mc)
            self.assertTrue(mc[key])

    def test_falsifiers_include_anticipation_and_n1(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        blob = " ".join(pkt["falsifiers_or_limits"]).lower()
        self.assertIn("anticipat", blob)
        self.assertIn("inventory", blob)
        self.assertIn("n=1", blob)


class TestDiscipline(_Base):
    def test_denominators_separated(self):
        self._seed_313()
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (10, '2026-04-05', 'realized', "
                "'none', 'Foo imposes bar', ?)", (_mt("FOO"),))
            conn.commit()
        pkt = P.build_packet(db_path=self._tmp)
        d = pkt["denominators"]
        self.assertEqual(d["archive_rows"], 2)
        self.assertEqual(d["accepted_coverage_denominator"], 1)
        self.assertEqual(d["staged_candidate_count"], 1)

    def test_non_claims_cover_required_ground(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        blob = " ".join(pkt["non_claims"]).lower()
        for needle in ("not accepted evidence", "no paid", "promot",
                       "significance", "family-level", "recommendation",
                       "denominator", "fdr", "illustrative"):
            self.assertIn(needle, blob)

    def test_stage_passthrough_no_promotion(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(pkt["candidate"]["stage"], "z1a_candidate_pack")


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt)
        text.encode("cp1252")
        low = text.lower()
        self.assertIn("direct vs supplier", low)
        self.assertIn("what this adds to the labor family", low)
        self.assertIn("partial", low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_313()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt) + " " + json.dumps(pkt)
        with open(os.path.join(_REPO, "scripts",
                               "uaw_supplier_transmission_packet.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade", r"\balpha\b"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


if __name__ == "__main__":
    unittest.main()
