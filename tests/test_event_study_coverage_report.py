"""Tests for ``scripts/event_study_coverage_report.py`` (E2).

Read-only report that loops ``event_study_validation.build_event_study_validation``
over the archive and surfaces the per-event point estimates the engine
already computes. Pins:

* a ready event surfaces per-horizon abnormal_return / sar / car;
* an insufficient event surfaces blocking_reasons and NO point estimates;
* available + insufficient counts sum to total_events;
* curated_intake (NON_ANALYSIS_STAGES) rows are excluded and disclosed;
* an empty archive is honest;
* ``--limit`` caps the per-event lists only — aggregates use the full set;
* the report mutates nothing and restores ``db.DB_FILE``;
* every payload carries an explicit non-claim block;
* the report imports no provider / network / FDR-pool seam and never reads
  demo_artifacts;
* ``--json`` / text CLI plumbing.

The ready-event fixture reuses the same seeding shape as
``tests/test_event_study_validation`` so the report is exercised against
the REAL gate, not a stub.
"""
from __future__ import annotations

import ast
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts import event_study_coverage_report as report  # noqa: E402


# ---------------------------------------------------------------------------
# Seeding helpers (mirror tests/test_event_study_validation)
# ---------------------------------------------------------------------------

_EVENT_D = date(2026, 3, 16)  # a Monday
_EVENT_ISO = _EVENT_D.isoformat()


def _bdays_before(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    out.reverse()
    return out


def _bdays_after(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


def _close(i: int, base: float, *, noise: bool = True, jump_from: int | None = None) -> float:
    val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
    if jump_from is not None and i >= jump_from:
        val *= 1.04
    return round(val, 4)


def _ready_price_rows() -> list[tuple]:
    """(ticker, iso_date, close, auto_adjust) making XLE event_study_available."""
    pre = _bdays_before(_EVENT_D, 65)
    post = _bdays_after(_EVENT_D, 25)
    dates = pre + [_EVENT_D] + post
    event_index = len(pre)
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        rows.append(("SPY", d.isoformat(), _close(i, 100.0, noise=False), 0))
        rows.append(("XLE", d.isoformat(), _close(i, 50.0, jump_from=event_index + 1), 0))
    return rows


def _make_db(events: list[tuple], price_rows: list[tuple]) -> str:
    """events: (id, headline, event_date, market_tickers, stage).
    price_rows: (ticker, iso_date, close, auto_adjust)."""
    path = os.path.join(tempfile.gettempdir(), f"test_es_cov_{uuid.uuid4().hex}.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, "
            "event_date TEXT, market_tickers TEXT, stage TEXT)"
        )
        conn.executemany(
            "INSERT INTO events (id, headline, event_date, market_tickers, stage) "
            "VALUES (?, ?, ?, ?, ?)",
            events,
        )
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "PRIMARY KEY (ticker, date, auto_adjust))"
        )
        conn.executemany(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, "
            "fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(t, d, c, 1000.0, aa, "2026-01-01T00:00:00") for (t, d, c, aa) in price_rows],
        )
        conn.commit()
    finally:
        conn.close()
    return path


_XLE_TICKERS = '[{"symbol": "XLE"}]'


class CoverageReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = _make_db(
            events=[
                (1, "Ready XLE event", _EVENT_ISO, _XLE_TICKERS, "realized"),
                (2, "No ticker event", _EVENT_ISO, "[]", "realized"),
                (3, "Curated stub", _EVENT_ISO, None, db.CURATED_INTAKE_STAGE),
            ],
            price_rows=_ready_price_rows(),
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _summary(self, **kw):
        return report.summarize_event_study_coverage(db_path=self.db_path, **kw)

    def test_ready_event_surfaces_point_estimates(self) -> None:
        s = self._summary()
        self.assertEqual(s["event_study_available_count"], 1)
        ready = s["available"][0]
        self.assertEqual(ready["event_id"], 1)
        self.assertEqual(ready["headline"], "Ready XLE event")
        self.assertEqual(ready["event_date"], _EVENT_ISO)
        self.assertEqual(ready["primary_ticker"], "XLE")
        self.assertEqual(ready["benchmark"], "SPY")
        self.assertIsInstance(ready["estimation_window_used"], int)
        horizons = {h["horizon"]: h for h in ready["per_horizon"]}
        self.assertEqual(set(horizons), {1, 5, 20})
        for h in (1, 5, 20):
            self.assertIsNotNone(horizons[h]["abnormal_return"])
            self.assertIsNotNone(horizons[h]["sar"])
            self.assertIsNotNone(horizons[h]["car"])

    def test_insufficient_event_surfaces_reasons_no_estimates(self) -> None:
        s = self._summary()
        self.assertEqual(s["insufficient_data_count"], 1)
        ins = s["insufficient"][0]
        self.assertEqual(ins["event_id"], 2)
        self.assertEqual(ins["headline"], "No ticker event")
        self.assertIn("no_primary_ticker", ins["blocking_reasons"])
        self.assertNotIn("per_horizon", ins)
        self.assertIn("no_primary_ticker", s["blocking_reasons"])
        self.assertEqual(s["blocking_reasons"]["no_primary_ticker"], 1)

    def test_counts_sum_to_total(self) -> None:
        s = self._summary()
        self.assertEqual(
            s["event_study_available_count"] + s["insufficient_data_count"],
            s["total_events"],
        )
        self.assertEqual(s["total_events"], 2)  # curated excluded

    def test_curated_intake_excluded_and_disclosed(self) -> None:
        s = self._summary()
        self.assertEqual(s["curated_intake_excluded_count"], 1)
        self.assertEqual(s["total_events"], 2)
        # The curated stub (id 3) must not appear in either list.
        ids = {r["event_id"] for r in s["available"]} | {
            r["event_id"] for r in s["insufficient"]
        }
        self.assertNotIn(3, ids)

    def test_auto_adjust_basis_summary(self) -> None:
        s = self._summary()
        self.assertEqual(s["auto_adjust_basis"]["matched"], 1)
        self.assertEqual(s["auto_adjust_basis"]["cross_flag"], 0)

    def test_non_claim_block_present(self) -> None:
        nc = self._summary()["non_claims"]
        for key in (
            "point_estimates_only",
            "no_confidence_interval_at_n1",
            "no_p_value_at_n1",
            "no_fdr_at_n1",
            "no_confirmed_or_validated_language",
            "does_not_touch_phase1_phase2_fdr_pools",
            "live_cache_provider_is_legacy_unknown_unless_separately_reported",
        ):
            self.assertTrue(nc[key], f"non_claim {key} should be True")
        self.assertIn("n=1", nc["notes"])

    def test_no_mutation_and_restores_db_file(self) -> None:
        original = db.DB_FILE

        def _counts():
            c = sqlite3.connect(self.db_path)
            try:
                return (
                    c.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0],
                    c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                )
            finally:
                c.close()

        before = _counts()
        self._summary()
        self._summary()
        after = _counts()
        self.assertEqual(before, after)
        self.assertEqual(db.DB_FILE, original, "db.DB_FILE must be restored")

    def test_main_json_emits_valid_payload(self) -> None:
        buf = StringIO()
        rc = report.main(["--json", "--db-path", self.db_path], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["total_events"], 2)
        self.assertEqual(payload["event_study_available_count"], 1)
        self.assertIn("non_claims", payload)

    def test_main_text_runs(self) -> None:
        buf = StringIO()
        rc = report.main(["--db-path", self.db_path], out=buf)
        self.assertEqual(rc, 0)
        self.assertIn("XLE", buf.getvalue())


class LimitTest(unittest.TestCase):
    def test_limit_caps_lists_only_not_aggregates(self) -> None:
        events = [(1, "Ready XLE event", _EVENT_ISO, _XLE_TICKERS, "realized")]
        for i in range(2, 8):  # 6 no-ticker insufficient events
            events.append((i, f"No ticker {i}", _EVENT_ISO, "[]", "realized"))
        path = _make_db(events=events, price_rows=_ready_price_rows())
        try:
            s = report.summarize_event_study_coverage(db_path=path, limit=2)
        finally:
            os.remove(path)
        # Aggregates reflect the full archive...
        self.assertEqual(s["total_events"], 7)
        self.assertEqual(s["insufficient_data_count"], 6)
        self.assertEqual(s["event_study_available_count"], 1)
        # ...but the surfaced lists are capped at the limit.
        self.assertLessEqual(len(s["insufficient"]), 2)
        self.assertLessEqual(len(s["available"]), 2)


class EmptyTest(unittest.TestCase):
    def test_empty_archive_is_honest(self) -> None:
        path = _make_db(events=[], price_rows=[])
        try:
            s = report.summarize_event_study_coverage(db_path=path)
        finally:
            os.remove(path)
        self.assertEqual(s["total_events"], 0)
        self.assertEqual(s["event_study_available_count"], 0)
        self.assertEqual(s["insufficient_data_count"], 0)
        self.assertEqual(s["available"], [])
        self.assertEqual(s["insufficient"], [])
        self.assertIn("non_claims", s)

    def test_missing_db_returns_empty_shape(self) -> None:
        s = report.summarize_event_study_coverage(
            db_path=os.path.join(tempfile.gettempdir(), f"nope_{uuid.uuid4().hex}.db"),
        )
        self.assertEqual(s["total_events"], 0)
        self.assertEqual(s["available"], [])

    def test_missing_db_does_not_create_file(self) -> None:
        # A clean clone has no events.db.  Running the report against a
        # missing path must NOT leave a stray empty events.db behind.
        missing = os.path.join(
            tempfile.gettempdir(), f"nocreate_es_{uuid.uuid4().hex}.db",
        )
        self.addCleanup(lambda: os.path.exists(missing) and os.remove(missing))
        self.assertFalse(os.path.exists(missing))
        s = report.summarize_event_study_coverage(db_path=missing)
        self.assertFalse(
            os.path.exists(missing),
            "report must not create a DB file on a missing path",
        )
        self.assertEqual(s["total_events"], 0)
        self.assertEqual(s["available"], [])


class IsolationTest(unittest.TestCase):
    def test_imports_no_provider_or_fdr_pool(self) -> None:
        src = (ROOT / "scripts" / "event_study_coverage_report.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("yfinance", "market_data", "market_check", "cohort_evidence"):
            self.assertNotIn(forbidden, imported, f"unexpected import: {forbidden}")

    def test_does_not_read_demo_artifacts_or_cohort_evidence(self) -> None:
        # The report's only I/O is sqlite (the events table) plus the
        # read-only gate (price_cache).  It opens NO files, so it cannot
        # read demo_artifacts / cohort_evidence artifacts.  (The docstring
        # names them only to DECLARE it avoids them; that's documentation,
        # not access — so we assert the real property: no open()/read_text
        # calls, and no cohort_evidence import.)  The cohort_evidence import
        # is also covered by test_imports_no_provider_or_fdr_pool.
        src = (ROOT / "scripts" / "event_study_coverage_report.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        file_read_calls: list[str] = []
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "open":
                    file_read_calls.append("open")
                elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "read_bytes"):
                    file_read_calls.append(func.attr)
            elif isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(file_read_calls, [], "report must not read files directly")
        self.assertNotIn("cohort_evidence", imported)

    def test_reuses_gate_not_reimplemented(self) -> None:
        src = (ROOT / "scripts" / "event_study_coverage_report.py").read_text(encoding="utf-8")
        self.assertIn("build_event_study_validation", src)


if __name__ == "__main__":
    unittest.main()
