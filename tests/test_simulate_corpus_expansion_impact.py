"""Z1A — simulate_corpus_expansion_impact: read-only pre-ingestion estimator.

Proves the simulator computes category/year/month splits, flags concentration when
one category/month dominates, estimates deep-cache / placebo contribution from
price_cache already present (NOT by fetching), flags candidates missing cached
history, labels EVERY output as pre-ingestion / estimate-only, and has no
provider/fetch/write code path.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import scripts.simulate_corpus_expansion_impact as S  # noqa: E402


def _cand(cid, date, cat, fam, ticker):
    return {
        "id": cid, "event_date": date, "title": f"event {cid}",
        "source_url": f"https://www.justice.gov/{cid}", "source_type": "court",
        "category": cat, "mechanism_family": fam,
        "mechanism_summary": "a regulatory action reprices the exposed name",
        "affected_assets": [{"ticker": ticker, "role": "exposed", "rationale": "exposure"}],
        "benchmark": "SPY", "placebo_feasibility_guess": "uncertain",
        "limitation_or_falsifier": "n = 1 descriptive read", "review_status": "candidate_only_not_ingested",
    }


def _write_candidates() -> str:
    cands = [
        _cand("a1", "2022-08-25", "antitrust_regulation", "regulation", "GOOGL"),
        _cand("a2", "2023-01-24", "antitrust_regulation", "regulation", "GOOGL"),
        _cand("a3", "2023-09-26", "antitrust_regulation", "regulation", "AMZN"),
        _cand("t1", "2018-07-06", "tariff", "tariff", "DBA"),
        _cand("s1", "2020-09-14", "export_controls", "supply_shock", "SMH"),
    ]
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="sim_cand_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"candidates": cands}, fh, sort_keys=False, allow_unicode=True)
    return path


def _make_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sim_db_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, event_date TEXT, market_tickers TEXT)")
    con.execute("CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, volume REAL, "
                "auto_adjust INTEGER, fetched_at TEXT, source_provider TEXT)")
    import json
    # two existing 2026 oil-window events (current concentration)
    con.execute("INSERT INTO events VALUES (?,?,?)", (1, "2026-04-10",
                json.dumps([{"symbol": "XLE", "role": "beneficiary"}])))
    con.execute("INSERT INTO events VALUES (?,?,?)", (2, "2026-04-11",
                json.dumps([{"symbol": "CVX", "role": "beneficiary"}])))
    # cache: GOOGL + SMH deep (300 rows), AAPL shallow (5), AMZN + DBA missing (0)
    rows = []
    for tk, n in (("GOOGL", 300), ("SMH", 300), ("AAPL", 5)):
        for i in range(n):
            rows.append((tk, f"2020-01-{(i % 28) + 1:02d}", 100.0 + i, 1.0, 0, "t", "x"))
    con.executemany("INSERT INTO price_cache VALUES (?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return path


class TestSimulator(unittest.TestCase):
    def setUp(self):
        self.cands = _write_candidates()
        self.db = _make_db()

    def tearDown(self):
        for p in (self.cands, self.db):
            try:
                os.remove(p)
            except OSError:
                pass

    def test_category_year_month_splits(self):
        est = S.build_estimate(self.cands, self.db)
        self.assertEqual(est["candidate_count"], 5)
        self.assertEqual(est["category_split"]["antitrust_regulation"], 3)
        self.assertEqual(est["category_split"]["tariff"], 1)
        self.assertEqual(est["year_split"]["2023"], 2)
        self.assertEqual(est["year_split"]["2018"], 1)
        self.assertEqual(est["month_split"]["2023-09"], 1)

    def test_flags_category_concentration_over_40pct(self):
        est = S.build_estimate(self.cands, self.db)
        # antitrust is 3/5 = 60% -> must warn
        joined = " ".join(est["warnings"]).lower()
        self.assertIn("antitrust_regulation", joined)
        self.assertTrue(any("concentrat" in w.lower() for w in est["warnings"]))

    def test_estimates_deep_cache_and_missing_cache_from_existing_price_cache(self):
        est = S.build_estimate(self.cands, self.db)
        missing = set(est["candidates_missing_cache"])
        self.assertIn("AMZN", missing)   # 0 cache rows
        self.assertIn("DBA", missing)    # 0 cache rows
        self.assertNotIn("GOOGL", missing)
        # deep-cache contribution counts GOOGL + SMH
        self.assertGreaterEqual(est["deep_cache_candidate_count"], 2)

    def test_outputs_labeled_pre_ingestion_estimate_only(self):
        est = S.build_estimate(self.cands, self.db)
        self.assertTrue(est["estimate_only"])
        self.assertIn("pre-ingestion", S.summarize(est).lower())
        self.assertIn("estimate", S.summarize(est).lower())

    def test_projected_concentration_present(self):
        est = S.build_estimate(self.cands, self.db)
        self.assertIn("current", est["month_concentration"])
        self.assertIn("projected", est["month_concentration"])
        self.assertIn("current", est["oil_concentration"])
        self.assertIn("projected", est["oil_concentration"])

    def test_module_has_no_provider_or_write_path(self):
        with open(os.path.join(_REPO, "scripts", "simulate_corpus_expansion_impact.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("import market_data", "from market_data", "fetch_daily",
                          "INSERT", "UPDATE ", "set_provider", "confirm_paid"):
            self.assertNotIn(forbidden, src, f"simulator must not reference {forbidden!r}")

    def test_cli_runs_read_only(self):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join("scripts", "simulate_corpus_expansion_impact.py"),
                            self.cands, "--db", self.db], cwd=_REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pre-ingestion", (r.stdout + r.stderr).lower())


if __name__ == "__main__":
    unittest.main()
