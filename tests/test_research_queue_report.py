"""Tests for ``scripts/research_queue_report.py`` (AT1).

Pin the read-only research-queue contract:

* The queue inspects ONLY ``stage='z1a_candidate_pack'`` staged rows.
* Per-candidate event-study readiness comes from the same gate as the
  live route (``event_study_validation.build_event_study_validation``);
  per-horizon AR/SAR/CAR point estimates surface when computable.
* Near-duplicate collisions are checked against the non-candidate,
  non-synthetic corpus only (a staged row never collides with itself,
  another staged row, or a synthetic seed).
* Each candidate gets exactly one deterministic classification:
  ``defer_near_duplicate`` > ``data_limited`` >
  ``defer_low_identification`` > ``needs_manual_review`` >
  ``ready_for_no_paid_review``.
* Every payload carries a ``non_claims`` block; nothing in the report is
  framed as advice to transact, a prediction, or a significance claim,
  and paid ``/analyze`` stays blocked.
* Read-only: no DB write, no provider, no LLM, no FastAPI surface.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import research_queue_report as queue_report  # noqa: E402


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    stage           TEXT
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

_EVENT_PROVENANCE_DDL = """
CREATE TABLE event_provenance (
    event_id        INTEGER PRIMARY KEY,
    source_type     TEXT,
    source_url      TEXT,
    intake_path     TEXT,
    created_at      TEXT
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

_STAGE_CANDIDATE = "z1a_candidate_pack"
_FETCHED_AT = "2026-05-06T12:00:00+00:00"

_NON_CLAIM_KEYS = (
    "not_a_trade_recommendation",
    "not_a_prediction",
    "no_statistical_significance_claim",
    "paid_analysis_remains_blocked",
    "notes",
)

_CLASSIFICATIONS = (
    queue_report.CLASS_READY,
    queue_report.CLASS_MANUAL,
    queue_report.CLASS_DUP,
    queue_report.CLASS_LOW_ID,
    queue_report.CLASS_DATA_LIMITED,
)


def _contiguous_window(event_date: date, n_pre: int, n_post: int) -> list[date]:
    pre: list[date] = []
    cur = event_date
    while len(pre) < n_pre:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            pre.append(cur)
    pre.reverse()
    post: list[date] = []
    cur = event_date
    while len(post) < n_post:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            post.append(cur)
    return pre + [event_date] + post


class _Base(unittest.TestCase):
    _ED = date(2026, 4, 15)

    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_rqr_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.execute(_EVENT_PROVENANCE_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed_event(
        self,
        *,
        stage: str = _STAGE_CANDIDATE,
        headline: str = "Regulator files antitrust suit against ExampleCo",
        event_date: str | None = None,
        ticker: str | None = "AAPL",
        event_id: int | None = None,
    ) -> int:
        tickers = (
            json.dumps([{"symbol": ticker}]) if ticker is not None else "[]"
        )
        ed = event_date if event_date is not None else self._ED.isoformat()
        with sqlite3.connect(self._tmp) as conn:
            if event_id is None:
                cur = conn.execute(
                    "INSERT INTO events (headline, event_date, market_tickers, "
                    "stage) VALUES (?, ?, ?, ?)",
                    (headline, ed, tickers, stage),
                )
                rid = int(cur.lastrowid)
            else:
                conn.execute(
                    "INSERT INTO events (id, headline, event_date, "
                    "market_tickers, stage) VALUES (?, ?, ?, ?, ?)",
                    (event_id, headline, ed, tickers, stage),
                )
                rid = event_id
            conn.commit()
            return rid

    def _seed_provenance(self, event_id: int, *, source_url: str) -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_provenance (event_id, source_type, "
                "source_url, intake_path, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, "regulator", source_url, _STAGE_CANDIDATE,
                 "2026-06-09T00:00:00"),
            )
            conn.commit()

    def _flag_synthetic(self, event_id: int) -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, "
                "override_reason, created_at) VALUES (?, ?, ?, ?)",
                (event_id, "synthetic_seed", "seed", "2026-06-09T00:00:00"),
            )
            conn.commit()

    def _seed_full_series(self, ticker: str, *, base: float = 50.0) -> None:
        """Matched-basis (aa=1) contiguous series for ``ticker`` and SPY so
        the event-study gate can compute every horizon."""
        dates = _contiguous_window(self._ED, 70, 25)
        with sqlite3.connect(self._tmp) as conn:
            for i, d in enumerate(dates):
                val = base * (1 + 0.0005 * i + 0.003 * ((-1) ** i))
                if i > 70:
                    val *= 1.04
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (ticker, d.isoformat(), round(val, 4), 1e6, 1, _FETCHED_AT),
                )
                bench = 100.0 * (1 + 0.0005 * i)
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("SPY", d.isoformat(), round(bench, 4), 1e6, 1, _FETCHED_AT),
                )
            conn.commit()

    def _summarize(self) -> dict:
        return queue_report.summarize_research_queue(db_path=self._tmp)


# ---------------------------------------------------------------------------
# Pure classifier
# ---------------------------------------------------------------------------


class TestClassifier(unittest.TestCase):
    _HORIZONS_OK = [
        {"horizon": 1, "abnormal_return": 0.01, "sar": 0.5, "car": 0.01},
        {"horizon": 5, "abnormal_return": 0.02, "sar": 0.6, "car": 0.02},
        {"horizon": 20, "abnormal_return": 0.03, "sar": 0.7, "car": 0.03},
    ]

    def _classify(self, **overrides) -> str:
        kwargs = dict(
            status="event_study_available",
            per_horizon=self._HORIZONS_OK,
            collisions=[],
            has_provenance=True,
            basis_matched=True,
        )
        kwargs.update(overrides)
        return queue_report.classify_candidate(**kwargs)

    def test_ready_when_everything_present(self) -> None:
        self.assertEqual(self._classify(), queue_report.CLASS_READY)

    def test_collision_defers_as_near_duplicate(self) -> None:
        result = self._classify(
            collisions=[{"event_id": 300, "reasons": ["headline_similarity"]}],
        )
        self.assertEqual(result, queue_report.CLASS_DUP)

    def test_collision_outranks_data_limited(self) -> None:
        result = self._classify(
            status="insufficient_data",
            per_horizon=[],
            collisions=[{"event_id": 300, "reasons": ["date_window_ticker"]}],
        )
        self.assertEqual(result, queue_report.CLASS_DUP)

    def test_insufficient_status_is_data_limited(self) -> None:
        result = self._classify(status="insufficient_data", per_horizon=[])
        self.assertEqual(result, queue_report.CLASS_DATA_LIMITED)

    def test_null_1d_abnormal_return_defers_low_identification(self) -> None:
        horizons = [dict(h) for h in self._HORIZONS_OK]
        horizons[0]["abnormal_return"] = None
        result = self._classify(per_horizon=horizons)
        self.assertEqual(result, queue_report.CLASS_LOW_ID)

    def test_missing_provenance_needs_manual_review(self) -> None:
        result = self._classify(has_provenance=False)
        self.assertEqual(result, queue_report.CLASS_MANUAL)

    def test_cross_flag_basis_needs_manual_review(self) -> None:
        result = self._classify(basis_matched=False)
        self.assertEqual(result, queue_report.CLASS_MANUAL)

    def test_partial_longer_horizon_needs_manual_review(self) -> None:
        horizons = [dict(h) for h in self._HORIZONS_OK]
        horizons[2]["abnormal_return"] = None
        result = self._classify(per_horizon=horizons)
        self.assertEqual(result, queue_report.CLASS_MANUAL)


# ---------------------------------------------------------------------------
# Queue scope
# ---------------------------------------------------------------------------


class TestQueueScope(_Base):
    def test_inspects_only_staged_candidates(self) -> None:
        staged = self._seed_event()
        self._seed_event(stage="realized", headline="Some accepted event")
        self._seed_event(stage="analysis_pending_review",
                         headline="A quarantined analyzed row")
        result = self._summarize()
        self.assertEqual(result["total_staged_candidates"], 1)
        self.assertEqual(
            [c["event_id"] for c in result["candidates"]], [staged],
        )
        self.assertEqual(result["queue_stage"], _STAGE_CANDIDATE)

    def test_empty_queue_zero_counts(self) -> None:
        self._seed_event(stage="realized")
        result = self._summarize()
        self.assertEqual(result["total_staged_candidates"], 0)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(
            sum(result["classification_counts"].values()), 0,
        )

    def test_missing_db_returns_empty_shape_without_creating_file(self) -> None:
        missing = os.path.join(
            tempfile.gettempdir(), f"nocreate_rqr_{uuid.uuid4().hex}.db",
        )
        self.addCleanup(lambda: os.path.exists(missing) and os.remove(missing))
        result = queue_report.summarize_research_queue(db_path=missing)
        self.assertEqual(result["total_staged_candidates"], 0)
        self.assertFalse(os.path.exists(missing))


# ---------------------------------------------------------------------------
# End-to-end classification on fixtures
# ---------------------------------------------------------------------------


class TestEndToEnd(_Base):
    def test_ready_candidate_with_coverage_and_provenance(self) -> None:
        staged = self._seed_event(ticker="XLE")
        self._seed_provenance(staged, source_url="https://example.gov/a")
        self._seed_full_series("XLE")
        result = self._summarize()
        entry = result["candidates"][0]
        self.assertEqual(entry["classification"], queue_report.CLASS_READY)
        self.assertEqual(entry["event_study_status"], "event_study_available")
        horizons = {h["horizon"]: h for h in entry["per_horizon"]}
        for h in (1, 5, 20):
            self.assertIn(h, horizons)
            self.assertIsInstance(horizons[h]["abnormal_return"], float)
        self.assertEqual(
            result["classification_counts"][queue_report.CLASS_READY], 1,
        )

    def test_candidate_without_cache_is_data_limited(self) -> None:
        staged = self._seed_event(ticker="XLE")
        self._seed_provenance(staged, source_url="https://example.gov/a")
        result = self._summarize()
        entry = result["candidates"][0]
        self.assertEqual(
            entry["classification"], queue_report.CLASS_DATA_LIMITED,
        )
        self.assertTrue(entry["blocking_reasons"])

    def test_near_duplicate_of_existing_event_is_deferred(self) -> None:
        headline = "Commerce implements new export controls on chips"
        self._seed_event(
            stage="curated_observation", headline=headline, ticker="NVDA",
        )
        staged = self._seed_event(headline=headline, ticker="NVDA")
        self._seed_provenance(staged, source_url="https://example.gov/b")
        self._seed_full_series("NVDA")
        result = self._summarize()
        entry = result["candidates"][0]
        self.assertEqual(entry["classification"], queue_report.CLASS_DUP)
        self.assertTrue(entry["collisions"])
        reasons = {
            r for c in entry["collisions"] for r in c["reasons"]
        }
        self.assertIn("headline_similarity", reasons)

    def test_staged_candidates_do_not_collide_with_each_other(self) -> None:
        headline = "Regulator files suit against ExampleCo over pricing"
        a = self._seed_event(headline=headline, ticker="AAPL")
        b = self._seed_event(headline=headline, ticker="AAPL")
        for rid in (a, b):
            self._seed_provenance(rid, source_url=f"https://example.gov/{rid}")
        result = self._summarize()
        for entry in result["candidates"]:
            self.assertEqual(entry["collisions"], [])
            self.assertNotEqual(
                entry["classification"], queue_report.CLASS_DUP,
            )

    def test_synthetic_seed_rows_are_not_collision_targets(self) -> None:
        headline = "OPEC slashes output beyond expectations"
        seed = self._seed_event(stage="realized", headline=headline,
                                ticker="AAPL")
        self._flag_synthetic(seed)
        staged = self._seed_event(headline=headline, ticker="AAPL")
        self._seed_provenance(staged, source_url="https://example.gov/c")
        result = self._summarize()
        entry = result["candidates"][0]
        self.assertEqual(entry["collisions"], [])

    def test_provenance_surfaces_on_candidate_entry(self) -> None:
        staged = self._seed_event()
        self._seed_provenance(staged, source_url="https://example.gov/d")
        entry = self._summarize()["candidates"][0]
        self.assertEqual(
            entry["provenance"]["source_url"], "https://example.gov/d",
        )
        self.assertEqual(entry["provenance"]["intake_path"], _STAGE_CANDIDATE)


# ---------------------------------------------------------------------------
# Non-claims + output modes
# ---------------------------------------------------------------------------


class TestNonClaimsAndCli(_Base):
    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = queue_report.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def test_non_claims_block_present(self) -> None:
        self._seed_event()
        result = self._summarize()
        for key in _NON_CLAIM_KEYS:
            self.assertIn(key, result["non_claims"], f"missing: {key}")

    def test_classification_counts_cover_every_class(self) -> None:
        self._seed_event()
        counts = self._summarize()["classification_counts"]
        for cls in _CLASSIFICATIONS:
            self.assertIn(cls, counts)

    def test_json_cli_output_parses(self) -> None:
        staged = self._seed_event()
        self._seed_provenance(staged, source_url="https://example.gov/e")
        rc, output = self._run_cli(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_staged_candidates"], 1)
        self.assertIn("non_claims", body)

    def test_text_cli_output_names_queue_and_non_claims(self) -> None:
        self._seed_event()
        rc, output = self._run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        self.assertIn(_STAGE_CANDIDATE, output)
        self.assertIn("paid", output.lower())
        self.assertIn("not", output.lower())


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


class TestReadOnly(_Base):
    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        staged = self._seed_event(ticker="XLE")
        self._seed_provenance(staged, source_url="https://example.gov/f")
        self._seed_full_series("XLE")

        def snapshot() -> list:
            conn = sqlite3.connect(self._tmp)
            try:
                out = []
                for table in ("events", "price_cache", "event_provenance",
                              "event_hygiene"):
                    out.append(list(conn.execute(f"SELECT * FROM {table}")))
                return out
            finally:
                conn.close()

        before = snapshot()
        for _ in range(2):
            self._summarize()
        self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()
