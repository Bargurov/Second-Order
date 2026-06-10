"""Tests for scripts/uaw_supplier_backfill_gate.py (read-only gate/design).

The backfill gate turns the C2A lesson into a durable contract: rows-exist is
not compute-ready. It measures the exact bounded LEA/APTV pre-event gap for
staged candidate 313, defines what a future bounded backfill would be allowed
to write, requires a safety sequence before any live mutation, and approves
nothing - no DB write, no paid/provider call, no promotion.
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
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import uaw_supplier_backfill_gate as G  # noqa: E402


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
_EVENT_DAY = date(2023, 9, 15)


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


def _file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_uaw_gate_{uuid.uuid4().hex}.db",
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

    def _seed_series(self, ticker, dates, base=100.0, noise=True):
        with sqlite3.connect(self._tmp) as conn:
            for i, d in enumerate(dates):
                val = base * (1 + 0.0005 * i
                              + (0.003 * ((-1) ** i) if noise else 0.0))
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,0,'t')",
                    (ticker, d.isoformat(), val, 1.0e6),
                )
            conn.commit()

    def _seed_2026_only(self, ticker, n=20):
        days = _bdays_around(date(2026, 3, 2), 0, n - 1)
        self._seed_series(ticker, days)

    def _seed_live_like(self):
        self._seed_313()
        dates = _bdays_around(_EVENT_DAY, 80, 35)
        self._seed_series("SPY", dates, base=440.0, noise=False)
        self._seed_series("GM", dates, base=33.0)
        self._seed_series("F", dates, base=12.0)
        self._seed_2026_only("LEA")
        self._seed_2026_only("APTV")

    def _coverage(self, gate, ticker):
        for row in gate["coverage"]:
            if row["ticker"] == ticker:
                return row
        raise AssertionError(f"coverage row for {ticker} missing")


class TestGateScope(_Base):
    def test_identifies_candidate_313_uaw_case(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        self.assertEqual(gate["gate_status"], "ok")
        scope = gate["gate_scope"]
        self.assertEqual(scope["event_id"], 313)
        self.assertEqual(scope["event_date"], "2023-09-15")
        self.assertEqual(scope["mechanism_family"], "labor_inflation")
        self.assertEqual(scope["direct_oem_tickers"], ["GM", "F"])
        self.assertEqual(scope["supplier_tickers"], ["LEA", "APTV"])
        self.assertEqual(scope["target_table"], "price_cache")
        self.assertEqual(scope["mutation_status"], "not_approved")

    def test_blocked_when_candidate_missing(self):
        gate = G.build_gate(db_path=self._tmp)
        self.assertEqual(gate["gate_status"], "candidate_not_found")

    def test_blocked_when_candidate_not_staged(self):
        self._seed_313(stage="realized")
        gate = G.build_gate(db_path=self._tmp)
        self.assertEqual(gate["gate_status"], "blocked_candidate_not_staged")

    def test_suppliers_arg_respected(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp, suppliers=("LEA",))
        self.assertEqual(gate["gate_scope"]["supplier_tickers"], ["LEA"])
        self.assertEqual(gate["future_backfill_plan"]["allowed_tickers"],
                         ["LEA"])


class TestCoverage(_Base):
    def test_gm_and_f_recognized_compute_ready(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        for t in ("GM", "F"):
            row = self._coverage(gate, t)
            self.assertTrue(row["rows_exist"], t)
            self.assertTrue(row["compute_ready"], t)
            self.assertTrue(row["has_estimation_window_coverage"], t)
            self.assertTrue(row["has_event_window_coverage"], t)

    def test_lea_aptv_present_but_not_compute_ready(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        for t in ("LEA", "APTV"):
            row = self._coverage(gate, t)
            self.assertTrue(row["rows_exist"], t)
            self.assertGreater(row["local_row_count"], 0, t)
            self.assertEqual(row["pre_event_distinct_dates"], 0, t)
            self.assertFalse(row["compute_ready"], t)
            self.assertFalse(row["has_estimation_window_coverage"], t)
            self.assertTrue(row["reason_if_not_compute_ready"], t)

    def test_event_window_coverage_not_satisfied_by_far_future_rows(self):
        # 2026-only rows sit after the event date but far outside the event
        # window - they must not count as event-window coverage.
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        for t in ("LEA", "APTV"):
            row = self._coverage(gate, t)
            self.assertFalse(row["has_event_window_coverage"], t)

    def test_rows_exist_is_separated_from_compute_ready(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        lea = self._coverage(gate, "LEA")
        self.assertTrue(lea["rows_exist"])
        self.assertFalse(lea["compute_ready"])
        text = G._render_text(gate).lower()
        self.assertIn("rows-exist is not compute-ready", text)

    def test_pre_event_distinct_dates_surfaced_per_ticker(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        self.assertEqual(self._coverage(gate, "GM")["pre_event_distinct_dates"],
                         80)
        self.assertEqual(self._coverage(gate, "LEA")["pre_event_distinct_dates"],
                         0)
        self.assertEqual(self._coverage(gate, "SPY")["pre_event_distinct_dates"],
                         80)

    def test_coverage_reports_row_counts_and_date_span(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        lea = self._coverage(gate, "LEA")
        self.assertEqual(lea["local_row_count"], 20)
        self.assertTrue(lea["min_date"].startswith("2026-"))
        self.assertTrue(lea["max_date"].startswith("2026-"))


class TestReadout(_Base):
    def test_direct_oem_readout_available_and_descriptive(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        ro = gate["current_readout"]
        self.assertTrue(ro["descriptive_only"])
        self.assertTrue(ro["n_equals_one"])
        for t in ("GM", "F"):
            leg = ro["direct_oem_readout"][t]
            self.assertEqual(leg["status"], "event_study_available")
            self.assertEqual(len(leg["horizons"]), 3)

    def test_supplier_readout_status_says_not_computable(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        status = gate["current_readout"]["supplier_readout_status"].lower()
        self.assertIn("not computable", status)
        self.assertIn("lea", status)
        self.assertIn("aptv", status)


class TestFutureBackfillPlan(_Base):
    def test_backfill_scope_is_bounded(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        plan = gate["future_backfill_plan"]
        self.assertEqual(plan["allowed_tickers"], ["LEA", "APTV"])
        rng = plan["allowed_date_range"]
        self.assertLess(rng["start"], "2023-09-15")
        self.assertGreater(rng["start"], "2023-04-01")
        self.assertGreater(rng["end"], "2023-09-15")
        self.assertLess(rng["end"], "2023-12-31")
        self.assertTrue(plan["forbidden_scope"])
        self.assertTrue(plan["expected_purpose"])

    def test_expected_rows_derived_from_benchmark_calendar(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        plan = gate["future_backfill_plan"]
        # 75 pre-event bars (60 estimation + 15 buffer) + event day +
        # 30 post-event bars (20 horizon + 10 buffer) = 106 trading days
        self.assertEqual(plan["expected_rows_per_ticker"], 106)
        self.assertEqual(plan["expected_total_rows_max"], 212)
        rng = plan["allowed_date_range"]
        self.assertIn("SPY", rng["calendar_basis"])

    def test_expected_rows_fall_back_without_benchmark_calendar(self):
        self._seed_313()
        gate = G.build_gate(db_path=self._tmp)
        plan = gate["future_backfill_plan"]
        rng = plan["allowed_date_range"]
        self.assertIn("weekday", rng["calendar_basis"].lower())
        self.assertEqual(plan["expected_rows_per_ticker"], 106)
        self.assertLess(rng["start"], "2023-09-15")
        self.assertGreater(rng["end"], "2023-09-15")

    def test_plan_forbids_paid_provider_analyze_promotion(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        plan = gate["future_backfill_plan"]
        self.assertTrue(plan["no_paid_provider"])
        self.assertTrue(plan["no_analyze"])
        self.assertTrue(plan["no_promotion"])
        self.assertTrue(plan["separate_approval_required"])
        blob = " ".join(plan["forbidden_scope"]).lower()
        self.assertIn("paid", blob)
        self.assertIn("ticker", blob)


class TestSafetySequence(_Base):
    def test_safety_sequence_has_all_required_steps(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        seq = gate["required_safety_sequence_before_mutation"]
        for step in ("clean_tree_check", "db_hash_before",
                     "local_backup_required",
                     "temp_db_or_snapshot_preview_required",
                     "dry_run_expected_rows", "targeted_tests_required",
                     "live_probe_required",
                     "db_hash_after_or_expected_mutation_report",
                     "staged_files_check"):
            self.assertIn(step, seq)
            self.assertTrue(seq[step])

    def test_mutation_requires_separate_operator_approval(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        self.assertEqual(gate["gate_scope"]["mutation_status"], "not_approved")
        self.assertTrue(
            gate["future_backfill_plan"]["separate_approval_required"])
        text = G._render_text(gate).lower()
        self.assertIn("separate operator approval", text)


class TestDiscipline(_Base):
    def test_build_gate_does_not_write_to_database(self):
        self._seed_live_like()
        before = _file_sha256(self._tmp)
        G.build_gate(db_path=self._tmp)
        self.assertEqual(_file_sha256(self._tmp), before)

    def test_denominators_separated(self):
        self._seed_313()
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (10, '2026-04-05', 'realized', "
                "'none', 'Foo imposes bar', ?)", (_mt("FOO"),))
            conn.commit()
        gate = G.build_gate(db_path=self._tmp)
        d = gate["denominators"]
        self.assertEqual(d["archive_rows"], 2)
        self.assertEqual(d["accepted_coverage_denominator"], 1)
        self.assertEqual(d["staged_candidate_count"], 1)

    def test_stage_passthrough_no_promotion(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        self.assertEqual(gate["gate_scope"]["stage"], "z1a_candidate_pack")
        self.assertEqual(gate["gate_scope"]["corpus_status"], "staged")

    def test_supplier_effects_not_implied_observed(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        cannot = " ".join(gate["what_cannot_be_read_now"]).lower()
        self.assertIn("supplier", cannot)
        non_claims = " ".join(gate["non_claims"]).lower()
        self.assertIn("not computable", non_claims)
        self.assertNotIn("will show", non_claims)

    def test_non_claims_cover_required_ground(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        blob = " ".join(gate["non_claims"]).lower()
        for needle in ("not computable", "rows-exist", "no db mutation",
                       "no paid", "provider", "promot", "significance",
                       "family-level", "recommendation", "denominator",
                       "fdr"):
            self.assertIn(needle, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        text = G._render_text(gate)
        text.encode("cp1252")
        low = text.lower()
        for section in ("coverage", "rows-exist is not compute-ready",
                        "future bounded backfill scope",
                        "safety sequence before mutation",
                        "final disposition", "non-claims"):
            self.assertIn(section, low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_live_like()
        gate = G.build_gate(db_path=self._tmp)
        text = G._render_text(gate) + " " + json.dumps(gate)
        with open(os.path.join(_REPO, "scripts",
                               "uaw_supplier_backfill_gate.py"),
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
