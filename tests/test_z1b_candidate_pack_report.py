"""Z1B — copy-DB measurement report (tests).

Pins the read-only before/after measurement contract for
``scripts/z1b_candidate_pack_report.py``:

* ``snapshot(db_path)`` counts saved / market-scored / event-study-available
  events, beneficiary-loser role observations, and event-date-eligible /
  placebo-feasible observations on a given DB — read-only, on any path.
* ``build_before_after`` reports per-metric deltas plus candidate-specific
  event-study readiness, and every result is labelled copy-only / not promoted.
* The report carries the null/non-claim discipline: no significance, edge,
  signal, forecast, or alpha language anywhere in the module or its summary.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import db  # noqa: E402
from scripts import z1b_candidate_pack_report as R  # noqa: E402


def _seed_prices(con, ticker, dates, closes):
    con.executemany(
        "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?,?,?,?,0,?)",
        [(ticker, d, c, 2_000_000.0, "t") for d, c in zip(dates, closes)],
    )


def _new_db_with_ready_event() -> tuple[str, str]:
    """A temp DB with SPY + GOOGL deep history and ONE event-study-available
    event on GOOGL.  Returns (db_path, event_date_iso)."""
    orig = db.DB_FILE
    path = os.path.join(tempfile.gettempdir(), f"z1b_rep_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    db.DB_FILE = orig
    idx = [d.date().isoformat() for d in pd.bdate_range("2024-01-01", periods=100)]
    event_date = idx[70]
    con = sqlite3.connect(path)
    try:
        _seed_prices(con, "SPY", idx, [100 + i * 0.10 + ((i * 5) % 7) * 0.17 for i in range(len(idx))])
        _seed_prices(con, "GOOGL", idx, [120 + i * 0.13 + ((i * 7) % 11) * 0.21 for i in range(len(idx))])
        con.execute(
            "INSERT INTO events (timestamp, headline, stage, persistence, event_date, "
            "mechanism_family, market_tickers) VALUES (?,?,?,?,?,?,?)",
            ("t", "ready event", "z1a_candidate_pack", "unscored", event_date,
             "regulation", '[{"symbol": "GOOGL", "role": "exposed"}]'),
        )
        con.commit()
    finally:
        con.close()
    return path, event_date


def _write_pack(cands) -> str:
    import yaml
    path = os.path.join(tempfile.gettempdir(), f"z1b_rep_pack_{uuid.uuid4().hex}.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"candidates": cands}, fh, sort_keys=False, allow_unicode=True)
    return path


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def test_snapshot_counts_saved_scored_and_available(self):
        path, _ = _new_db_with_ready_event()
        self._paths.append(path)
        snap = R.snapshot(path, draws=20)
        self.assertEqual(snap["saved_events"], 1)
        self.assertEqual(snap["market_scored_events"], 1)
        self.assertEqual(snap["event_study_available"], 1)
        # keys present for the placebo-side denominators
        for k in ("role_observations", "event_date_eligible", "placebo_feasible"):
            self.assertIn(k, snap)
            self.assertIsInstance(snap[k], int)

    def test_snapshot_is_read_only(self):
        path, _ = _new_db_with_ready_event()
        self._paths.append(path)
        before = os.path.getmtime(path)
        R.snapshot(path, draws=20)
        # a read-only snapshot must not write the DB
        self.assertEqual(R.snapshot(path, draws=20)["saved_events"], 1)
        self.assertEqual(os.path.getmtime(path), before)


class TestBeforeAfter(unittest.TestCase):
    def setUp(self):
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _empty_db(self) -> str:
        orig = db.DB_FILE
        path = os.path.join(tempfile.gettempdir(), f"z1b_empty_{uuid.uuid4().hex}.db")
        db.DB_FILE = path
        db.init_db()
        db.DB_FILE = orig
        self._paths.append(path)
        return path

    def test_before_after_reports_positive_deltas(self):
        before = self._empty_db()
        after, ev_date = _new_db_with_ready_event()
        self._paths.append(after)
        pack = _write_pack([{
            "id": "doj-x", "event_date": ev_date, "title": "t",
            "source_url": "https://www.justice.gov/opa/pr/x", "source_type": "official",
            "category": "antitrust", "mechanism_family": "regulation",
            "mechanism_summary": "reprices regulatory risk on the named firm",
            "affected_assets": [{"ticker": "GOOGL", "role": "exposed", "rationale": "defendant"}],
            "benchmark": "SPY", "placebo_feasibility_guess": "uncertain",
            "limitation_or_falsifier": "n=1 descriptive read", "review_status": "candidate_only_not_ingested",
        }])
        self._paths.append(pack)
        rep = R.build_before_after(before, after, pack, draws=20)
        self.assertEqual(rep["deltas"]["saved_events"], 1)
        self.assertEqual(rep["deltas"]["event_study_available"], 1)
        self.assertTrue(rep["candidate_readiness"])

    def test_summary_labels_copy_only_and_not_promoted(self):
        before = self._empty_db()
        after, _ = _new_db_with_ready_event()
        self._paths.append(after)
        rep = R.build_before_after(before, after, None, draws=20)
        text = R.summarize(rep).lower()
        self.assertIn("copy", text)
        self.assertIn("not promoted", text)

    def test_no_significance_or_edge_language(self):
        before = self._empty_db()
        after, _ = _new_db_with_ready_event()
        self._paths.append(after)
        text = R.summarize(R.build_before_after(before, after, None, draws=20)).lower()
        with open(os.path.join(_REPO, "scripts", "z1b_candidate_pack_report.py"),
                  encoding="utf-8") as fh:
            src = fh.read().lower()
        for banned in ("significant", "edge", "signal", "forecast", "alpha", "proves", "outperform"):
            self.assertNotIn(banned, text, f"summary must not imply {banned!r}")
            self.assertNotIn(banned, src, f"report module must not use {banned!r}")


if __name__ == "__main__":
    unittest.main()
