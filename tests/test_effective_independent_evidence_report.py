"""
tests/test_effective_independent_evidence_report.py

K2 — effective independent evidence report (market-story clusters).

Contract under test:
* Pure, deterministic clustering core over synthetic fixtures: rows group
  when they share an event date, share a primary ticker within the 20d
  window, or carry an explicit duplicate link; connected components form
  descriptive "market-story clusters".
* Live report over the accepted track-record corpus (86): denominators
  preserved, reviewer-first markdown exhibit, representative-case overlay,
  missing readouts visible, read-only DB access, cp1252-safe, no
  inferential effective-n claim, no banned framing outside explicit
  non-claims.

NOTE on wording assertions below: banned-term literals appear here only as
test-guard machinery; the shipped artifacts must not carry them unnegated.
"""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from scripts.effective_independent_evidence_report import (  # noqa: E402
    build_clusters,
    build_report,
    max_non_overlapping_windows,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
# T1: live-archive checks are explicit opt-in via the shared gate;
# root events.db presence must not change the default universe.
from tests._local_data_gate import (  # noqa: E402
    local_data_skip_reason,
    local_events_db_or_none,
)
LIVE_DB = local_events_db_or_none()
STATS_MD = ROOT / "stats" / "EFFECTIVE_INDEPENDENT_EVIDENCE.md"

REPRESENTATIVE_IDS = {1, 46, 61, 66, 210, 211, 7, 29, 38, 71, 153, 154, 160, 212, 239}
MISSING_READOUT_IDS = [153, 154, 160]


def _row(event_id, date=None, ticker=None, duplicate_of=()):
    return {
        "event_id": event_id,
        "date": date,
        "primary_ticker": ticker,
        "duplicate_of": list(duplicate_of),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Pure clustering core — synthetic fixtures
# ---------------------------------------------------------------------------

class TestBuildClustersPure(unittest.TestCase):

    def test_same_date_rows_share_a_cluster(self):
        rows = [
            _row(1, "2026-04-05", "XLE"),
            _row(2, "2026-04-05", "GM"),
            _row(3, "2026-05-30", "NFLX"),
        ]
        clusters = build_clusters(rows)
        sizes = sorted(c["size"] for c in clusters)
        self.assertEqual(sizes, [1, 2])
        big = next(c for c in clusters if c["size"] == 2)
        self.assertEqual(big["event_ids"], [1, 2])

    def test_same_ticker_within_window_shares_a_cluster(self):
        rows = [
            _row(1, "2026-04-01", "XLE"),
            _row(2, "2026-04-15", "XLE"),
        ]
        clusters = build_clusters(rows, window_days=20)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["event_ids"], [1, 2])

    def test_same_ticker_beyond_window_stays_separate(self):
        rows = [
            _row(1, "2026-04-01", "XLE"),
            _row(2, "2026-05-30", "XLE"),
        ]
        clusters = build_clusters(rows, window_days=20)
        self.assertEqual(len(clusters), 2)

    def test_different_tickers_different_dates_stay_separate(self):
        rows = [
            _row(1, "2026-04-01", "XLE"),
            _row(2, "2026-04-02", "GM"),
        ]
        clusters = build_clusters(rows, window_days=20)
        self.assertEqual(len(clusters), 2)

    def test_duplicate_link_merges_rows(self):
        rows = [
            _row(1, "2026-04-01", "XLE"),
            _row(2, "2026-05-30", "GM", duplicate_of=[1]),
        ]
        clusters = build_clusters(rows)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["event_ids"], [1, 2])

    def test_transitive_chain_merges_into_one_cluster(self):
        # 1-2 share a date; 2-3 share a ticker within the window.
        rows = [
            _row(1, "2026-04-05", "GM"),
            _row(2, "2026-04-05", "XLE"),
            _row(3, "2026-04-20", "XLE"),
        ]
        clusters = build_clusters(rows, window_days=20)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["event_ids"], [1, 2, 3])

    def test_dateless_row_without_links_is_a_singleton(self):
        rows = [
            _row(1, None, "XLE"),
            _row(2, "2026-04-05", "XLE"),
        ]
        clusters = build_clusters(rows, window_days=20)
        self.assertEqual(len(clusters), 2)

    def test_cluster_sizes_sum_to_row_count(self):
        rows = [
            _row(1, "2026-04-05", "XLE"),
            _row(2, "2026-04-05", "GM"),
            _row(3, "2026-04-06", "XLE"),
            _row(4, "2026-05-30", None),
        ]
        clusters = build_clusters(rows)
        self.assertEqual(sum(c["size"] for c in clusters), len(rows))

    def test_output_is_deterministic_and_ordered(self):
        rows = [
            _row(5, "2026-04-05", "XLE"),
            _row(2, "2026-04-05", "GM"),
            _row(9, "2026-05-30", "NFLX"),
            _row(7, "2026-03-01", "GLD"),
        ]
        a = build_clusters(rows)
        b = build_clusters(list(reversed(rows)))
        self.assertEqual(a, b)
        # Ordered by size desc, then smallest member id; ids are stable.
        self.assertEqual(a[0]["size"], 2)
        self.assertEqual([c["cluster_id"] for c in a],
                         [f"c{i + 1:02d}" for i in range(len(a))])

    def test_cluster_carries_date_range_and_tickers(self):
        rows = [
            _row(1, "2026-04-05", "XLE"),
            _row(2, "2026-04-08", "XLE"),
        ]
        clusters = build_clusters(rows)
        c = clusters[0]
        self.assertEqual(c["date_min"], "2026-04-05")
        self.assertEqual(c["date_max"], "2026-04-08")
        self.assertIn("XLE", c["primary_tickers"])


class TestWindowCapacityPure(unittest.TestCase):

    def test_greedy_capacity_over_overlapping_windows(self):
        dates = ["2026-04-01", "2026-04-05", "2026-04-10", "2026-05-15"]
        self.assertEqual(max_non_overlapping_windows(dates, 20), 2)

    def test_distinct_dates_at_one_day_horizon_are_all_independent(self):
        dates = ["2026-04-01", "2026-04-05", "2026-04-10", "2026-05-15"]
        self.assertEqual(max_non_overlapping_windows(dates, 1), 4)

    def test_empty_input_yields_zero(self):
        self.assertEqual(max_non_overlapping_windows([], 20), 0)


# ---------------------------------------------------------------------------
# Live report — accepted track-record corpus
# ---------------------------------------------------------------------------

@unittest.skipUnless(LIVE_DB is not None, local_data_skip_reason())
class TestLiveReport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_before = _sha256(LIVE_DB)
        cls.report = build_report(db_path=str(LIVE_DB))
        cls.md = render_markdown(cls.report)

    @classmethod
    def tearDownClass(cls):
        assert _sha256(LIVE_DB) == cls.db_before, "events.db mutated by K2"

    def test_denominator_ledger_preserved(self):
        d = self.report["denominators"]
        self.assertEqual(d["archive_rows"], 180)
        self.assertEqual(d["accepted_coverage"], 94)
        self.assertEqual(d["accepted_track_record"], 86)
        self.assertEqual(d["event_study_available"], 78)
        self.assertEqual(d["event_study_denominator"], 94)
        self.assertEqual(d["staged_candidates"], 13)
        self.assertEqual(d["k2_lens"], "accepted_track_record")

    def test_nominal_rows_and_cluster_sum_invariant(self):
        s = self.report["cluster_summary"]
        self.assertEqual(s["nominal_rows"], 86)
        self.assertEqual(
            sum(c["size"] for c in self.report["clusters"]), 86,
        )

    def test_cluster_counts_are_present_and_consistent(self):
        s = self.report["cluster_summary"]
        self.assertGreaterEqual(s["cluster_count"], 1)
        self.assertLess(s["cluster_count"], 86)
        self.assertEqual(
            s["singleton_clusters"] + s["multi_row_clusters"],
            s["cluster_count"],
        )
        self.assertEqual(
            s["rows_in_multi_row_clusters"] + s["singleton_clusters"], 86,
        )
        self.assertGreaterEqual(s["largest_cluster_size"], 3)
        self.assertEqual(
            s["largest_cluster_size"],
            max(c["size"] for c in self.report["clusters"]),
        )

    def test_window_capacity_context_present(self):
        s = self.report["cluster_summary"]
        self.assertIn("max_non_overlapping_20d_windows", s)
        self.assertGreaterEqual(s["max_non_overlapping_20d_windows"], 1)
        self.assertLessEqual(s["max_non_overlapping_20d_windows"], 86)

    def test_largest_clusters_table_present(self):
        largest = self.report["largest_clusters"]
        self.assertTrue(largest)
        for c in largest:
            self.assertGreaterEqual(c["size"], 2)
            self.assertIn("event_ids", c)
            self.assertIn("outcome_split", c)
            self.assertIn("why_grouped", c)
            self.assertIn("interpretation_caution", c)

    def test_representative_overlay_covers_all_15_cases(self):
        overlay = self.report["representative_overlay"]
        ids = {c["event_id"] for c in overlay["cases"]}
        self.assertEqual(ids, REPRESENTATIVE_IDS)
        self.assertEqual(overlay["missing_readouts"], MISSING_READOUT_IDS)

    def test_cases_7_29_38_handled_explicitly(self):
        overlay = self.report["representative_overlay"]
        triplet = overlay["triplet_7_29_38"]
        self.assertIn("same_cluster", triplet)
        # These three share event date 2026-04-05 and the XLE primary, so
        # under the stated rules they must land in one cluster.
        self.assertTrue(triplet["same_cluster"])
        by_id = {c["event_id"]: c for c in overlay["cases"]}
        self.assertEqual(
            len({by_id[i]["cluster_id"] for i in (7, 29, 38)}), 1,
        )

    def test_markdown_opens_with_reviewer_takeaway(self):
        first_heading = None
        for line in self.md.splitlines():
            if line.startswith("## "):
                first_heading = line
                break
        self.assertIsNotNone(first_heading)
        self.assertIn("What a reviewer should take away first", first_heading)

    def test_markdown_states_rows_are_not_independent_stories(self):
        self.assertIn("not 86 independent market stories", self.md)

    def test_markdown_states_descriptive_not_inferential(self):
        self.assertIn("descriptive grouping, not inference", self.md)
        self.assertIn("not an inferential effective sample size", self.md)

    def test_markdown_carries_the_non_claim_line(self):
        self.assertIn(
            "not a p-value, an FDR pool, a score, a rank, a signal, "
            "a forecast, or a recommendation",
            self.md,
        )

    def test_every_effective_n_mention_is_negated(self):
        for line in self.md.lower().splitlines():
            if "effective n" in line or "effective sample" in line:
                self.assertTrue(
                    "not" in line or "no " in line,
                    f"unnegated effective-n mention: {line!r}",
                )

    def test_missing_readouts_visible_in_markdown(self):
        self.assertIn("153", self.md)
        self.assertIn("154", self.md)
        self.assertIn("160", self.md)

    def test_markdown_is_cp1252_safe(self):
        self.md.encode("cp1252")

    def test_report_and_markdown_are_deterministic(self):
        report2 = build_report(db_path=str(LIVE_DB))
        self.assertEqual(
            json.dumps(self.report, sort_keys=True, default=str),
            json.dumps(report2, sort_keys=True, default=str),
        )
        self.assertEqual(self.md, render_markdown(report2))

    def test_committed_stats_markdown_matches_current_render(self):
        self.assertTrue(STATS_MD.exists(), "stats exhibit missing")
        committed = STATS_MD.read_text(encoding="utf-8")
        self.assertEqual(committed.strip(), self.md.strip())

    def test_no_banned_framing_in_markdown(self):
        low = self.md.lower()
        for term in ("alpha", "proven", "statistically significant",
                     "strongest", "predictive", "winner", "loser", "worst",
                     "buy", "sell"):
            for line in low.splitlines():
                self.assertNotIn(
                    f" {term} ", f" {line} ",
                    f"banned term {term!r} in: {line!r}",
                )
        # Allowed only when negated / inside explicit non-claims:
        for term in ("proof", "signal", "forecast", "recommendation",
                     "performance", "best", "works"):
            for line in low.splitlines():
                if term in line.split() or f" {term}," in line or f" {term}." in line:
                    self.assertTrue(
                        "not" in line or "no " in line or "never" in line,
                        f"unnegated {term!r} in: {line!r}",
                    )


@unittest.skipUnless(LIVE_DB is not None, local_data_skip_reason())
class TestCli(unittest.TestCase):

    def test_json_mode_exits_cleanly_and_matches_core_counts(self):
        proc = subprocess.run(
            [sys.executable, "scripts/effective_independent_evidence_report.py",
             "--db-path", str(LIVE_DB), "--json"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        payload = json.loads(proc.stdout)
        expected = build_report(db_path=str(LIVE_DB))
        self.assertEqual(
            payload["cluster_summary"], expected["cluster_summary"],
        )
        self.assertEqual(payload["denominators"], expected["denominators"])

    def test_text_mode_exits_cleanly(self):
        proc = subprocess.run(
            [sys.executable, "scripts/effective_independent_evidence_report.py",
             "--db-path", str(LIVE_DB)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("What a reviewer should take away first", proc.stdout)


if __name__ == "__main__":
    unittest.main()
