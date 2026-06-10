"""Tests for scripts/candidate_paid_gate_packet.py (read-only).

The paid-gate packet must: stay read-only and no-paid; refuse to read as
approval (blocked by default, explicit future operator phrase required);
keep accepted vs staged separation explicit; classify assets conservatively
with live local-price-data flags; and degrade safely when the candidate is
promoted, missing, or unregistered.
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

from scripts import candidate_paid_gate_packet as P  # noqa: E402


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

_HEADLINE_304 = (
    "Justice Department sues Google for monopolizing digital advertising technologies"
)


def _mt(symbol):
    return json.dumps([{"symbol": symbol, "role": "exposed"}])


def _bdays_around(anchor: date, n_pre: int, n_post: int) -> list[date]:
    """Contiguous business days: n_pre before anchor, anchor, n_post after."""
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
            tempfile.gettempdir(), f"test_cpgp_{uuid.uuid4().hex}.db",
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

    def _seed(self, event_id, *, stage="z1a_candidate_pack", family="regulation",
              event_date="2023-01-24", headline=_HEADLINE_304, ticker="GOOGL"):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, stage, mechanism_family, "
                "headline, market_tickers) VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(ticker)),
            )
            conn.commit()

    def _seed_series(self, ticker, dates, base=100.0, noise=True, jump_from=None):
        with sqlite3.connect(self._tmp) as conn:
            for i, d in enumerate(dates):
                val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
                if jump_from is not None and i >= jump_from:
                    val *= 0.96
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?,?,?,?,0,'t')",
                    (ticker, d.isoformat(), val, 5_000_000.0),
                )
            conn.commit()

    def _seed_compute_ready_304(self):
        anchor = date(2023, 1, 24)
        dates = _bdays_around(anchor, 65, 22)
        self._seed(304)
        self._seed_series("GOOGL", dates, base=90.0, noise=True, jump_from=66)
        self._seed_series("SPY", dates, base=400.0, noise=False)


class TestPacketBasics(_Base):
    def test_packet_for_staged_candidate_basic_shape(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "ok")
        c = pkt["candidate"]
        self.assertEqual(c["id"], 304)
        self.assertEqual(c["stage"], "z1a_candidate_pack")
        self.assertEqual(c["date"], "2023-01-24")
        self.assertEqual(c["mechanism_family"], "regulation")
        self.assertEqual(c["primary_ticker"], "GOOGL")
        self.assertTrue(c["staged_no_paid"])
        rs = pkt["repo_data_status"]
        self.assertTrue(rs["db_read_only"])
        self.assertFalse(rs["paid_calls_made"])
        self.assertFalse(rs["analyze_ran"])
        self.assertTrue(rs["db_sha256"])

    def test_blocked_when_candidate_promoted(self):
        self._seed(304, stage="realized")
        pkt = P.build_packet(304, db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "blocked_candidate_not_staged")
        self.assertFalse(pkt["candidate"]["staged_no_paid"])
        self.assertEqual(pkt["recommendation"]["decision"], "defer_paid_analysis")
        # The gate never opens, even when blocked for other reasons.
        self.assertEqual(pkt["paid_gate"]["status"], "blocked_by_default")

    def test_candidate_not_found(self):
        pkt = P.build_packet(304, db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "candidate_not_found")
        self.assertEqual(pkt["recommendation"]["decision"], "defer_paid_analysis")

    def test_no_packet_registered_for_unknown_candidate(self):
        self._seed(999, headline="Some other staged candidate", ticker="XYZ")
        pkt = P.build_packet(999, db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "no_packet_registered")
        self.assertEqual(pkt["recommendation"]["decision"], "defer_paid_analysis")


class TestRecommendationLogic(_Base):
    def test_eligible_when_staged_distinct_and_compute_ready(self):
        self._seed_compute_ready_304()
        pkt = P.build_packet(304, db_path=self._tmp)
        self.assertEqual(pkt["packet_status"], "ok")
        self.assertTrue(pkt["local_readout"]["available"])
        self.assertEqual(len(pkt["local_readout"]["horizons"]), 3)
        self.assertTrue(pkt["local_readout"]["descriptive_only"])
        self.assertTrue(pkt["local_readout"]["n_equals_one"])
        self.assertEqual(
            pkt["recommendation"]["decision"],
            "eligible_for_future_paid_gate_design_only",
        )

    def test_requires_more_review_when_readout_unavailable(self):
        self._seed(304)  # no price data at all
        pkt = P.build_packet(304, db_path=self._tmp)
        self.assertFalse(pkt["local_readout"]["available"])
        self.assertEqual(
            pkt["recommendation"]["decision"], "requires_more_no_paid_review",
        )


class TestPaidGateDiscipline(_Base):
    def test_gate_blocked_by_default_and_never_reads_as_approved(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        gate = pkt["paid_gate"]
        self.assertEqual(gate["status"], "blocked_by_default")
        self.assertTrue(gate["backup_required"])
        self.assertTrue(gate["dry_run_required"])
        self.assertIn("304", gate["future_required_operator_phrase"])
        self.assertTrue(gate["expected_mutation_scope"])
        self.assertTrue(gate["stop_conditions"])
        # No string value anywhere in the gate may read as a granted approval.
        for v in json.dumps(gate).lower().split('"'):
            self.assertNotEqual(v.strip(), "approved")

    def test_non_claims_cover_required_ground(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        blob = " ".join(pkt["non_claims"]).lower()
        for needle in ("no paid", "not accepted evidence", "n=1", "significance",
                       "not a recommendation", "denominator", "fdr", "promot"):
            self.assertIn(needle, blob)

    def test_accepted_vs_staged_separation_explicit(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        sep = pkt["candidate"]["separation_note"].lower()
        self.assertIn("staged", sep)
        self.assertIn("accepted", sep)
        self.assertIn("excluded", sep)


class TestAssetProxyDiscipline(_Base):
    def test_categories_present_disjoint_and_price_flagged(self):
        self._seed(304)
        # GOOGL has one cache row; second-order names have none.
        self._seed_series("GOOGL", [date(2023, 1, 25)])
        pkt = P.build_packet(304, db_path=self._tmp)
        amap = pkt["asset_proxy_map"]
        cats = ("primary_defendant", "potential_second_order_assets",
                "noisy_or_context_assets", "excluded_assets")
        seen: set[str] = set()
        for cat in cats:
            self.assertIn(cat, amap)
            for entry in amap[cat]:
                self.assertIn("ticker", entry)
                self.assertIn("local_price_data", entry)
                self.assertIsInstance(entry["local_price_data"], bool)
                self.assertNotIn(entry["ticker"], seen)  # disjoint
                seen.add(entry["ticker"])
        primary = [e["ticker"] for e in amap["primary_defendant"]]
        self.assertEqual(primary, ["GOOGL"])
        self.assertTrue(amap["primary_defendant"][0]["local_price_data"])
        # Second-order names without local data must say so.
        for entry in amap["potential_second_order_assets"]:
            self.assertFalse(entry["local_price_data"])
        excluded = {e["ticker"] for e in amap["excluded_assets"]}
        self.assertIn("GOOG", excluded)
        self.assertTrue(amap["eligibility_notes"])


class TestDuplicateThreadCheck(_Base):
    def test_clean_fixture_concludes_distinct(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        dup = pkt["duplicate_thread_check"]
        for key in ("exact_duplicate_found", "near_thread_siblings",
                    "existing_google_antitrust_rows", "date_window_neighbors",
                    "conclusion"):
            self.assertIn(key, dup)
        self.assertFalse(dup["exact_duplicate_found"])
        self.assertTrue(dup["conclusion"].startswith("distinct"))

    def test_planted_same_date_same_ticker_duplicate_flags(self):
        self._seed(304)
        self._seed(900, stage="realized",
                   headline="Justice Department sues Google over ad market",
                   ticker="GOOGL")
        pkt = P.build_packet(304, db_path=self._tmp)
        dup = pkt["duplicate_thread_check"]
        self.assertTrue(dup["exact_duplicate_found"])
        self.assertNotEqual(dup["conclusion"][:8], "distinct")


class TestRenderingAndFraming(_Base):
    def test_text_render_cp1252_safe_and_states_blocked(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        text = P._render_text(pkt)
        text.encode("cp1252")
        low = text.lower()
        self.assertIn("blocked", low)
        self.assertIn("staged", low)
        self.assertIn("no-paid", low)

    def test_banned_framing_absent_from_output_and_source(self):
        self._seed(304)
        pkt = P.build_packet(304, db_path=self._tmp)
        text = P._render_text(pkt) + " " + json.dumps(pkt)
        with open(os.path.join(_REPO, "scripts", "candidate_paid_gate_packet.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


if __name__ == "__main__":
    unittest.main()
