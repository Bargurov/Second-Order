"""Tests for macro_surprise.classify_macro_surprise().

All tests are pure / offline — no network, no mocks of external services.
"""
import unittest

from macro_surprise import classify_macro_surprise


def _release(name: str, days_until: int) -> dict:
    status = (
        "today" if days_until == 0
        else "upcoming" if days_until > 0
        else "recent" if days_until >= -2
        else "past"
    )
    return {
        "name": name,
        "release_date": "2026-04-10",
        "period": "Mar 2026",
        "status": status,
        "days_until": days_until,
    }


def _cluster(headline: str) -> dict:
    return {"headline": headline, "source_count": 2}


class TestUpcomingRelease(unittest.TestCase):
    def test_upcoming_release_has_null_signal(self):
        releases = [_release("CPI", 3)]
        result = classify_macro_surprise(releases, [])
        self.assertIsNone(result[0]["surprise_signal"])
        self.assertIsNone(result[0]["headline_evidence"])


class TestBeatSignal(unittest.TestCase):
    def test_cpi_beat_headline_returns_beat(self):
        releases = [_release("CPI", 0)]
        clusters = [_cluster("US CPI rose 3.2%, above the 3.0% consensus")]
        result = classify_macro_surprise(releases, clusters)
        self.assertEqual(result[0]["surprise_signal"], "beat")
        self.assertIsNotNone(result[0]["headline_evidence"])


class TestMissSignal(unittest.TestCase):
    def test_nfp_miss_headline_returns_miss(self):
        releases = [_release("NFP", -1)]
        clusters = [_cluster("Nonfarm payrolls miss estimates, adding fewer jobs than expected")]
        result = classify_macro_surprise(releases, clusters)
        self.assertEqual(result[0]["surprise_signal"], "miss")


class TestInLineSignal(unittest.TestCase):
    def test_pce_in_line_headline_returns_in_line(self):
        releases = [_release("PCE", -2)]
        clusters = [_cluster("PCE inflation in line with expectations for February")]
        result = classify_macro_surprise(releases, clusters)
        self.assertEqual(result[0]["surprise_signal"], "in_line")


class TestNoMatchingCluster(unittest.TestCase):
    def test_in_window_release_with_no_cluster_returns_unknown(self):
        releases = [_release("PPI", -1)]
        clusters = [_cluster("Fed signals caution on rate cuts amid global uncertainty")]
        result = classify_macro_surprise(releases, clusters)
        self.assertEqual(result[0]["surprise_signal"], "unknown")
        self.assertIsNone(result[0]["headline_evidence"])


class TestIndicatorRequiredForMatch(unittest.TestCase):
    def test_direction_keyword_without_indicator_keyword_gives_unknown(self):
        # Headline has "beat" but no CPI/PPI/etc. indicator keyword
        releases = [_release("CPI", 0)]
        clusters = [_cluster("Tech stocks beat earnings expectations in Q1")]
        result = classify_macro_surprise(releases, clusters)
        self.assertEqual(result[0]["surprise_signal"], "unknown")


class TestWindowBoundary(unittest.TestCase):
    def test_days_until_minus_3_is_in_window(self):
        releases = [_release("Unemployment", -3)]
        clusters = [_cluster("Unemployment rate exceeds forecasts as jobless rate rises")]
        result = classify_macro_surprise(releases, clusters)
        self.assertEqual(result[0]["surprise_signal"], "beat")

    def test_days_until_minus_4_is_out_of_window(self):
        releases = [_release("CPI", -4)]
        clusters = [_cluster("CPI beat expectations significantly")]
        result = classify_macro_surprise(releases, clusters)
        self.assertIsNone(result[0]["surprise_signal"])


class TestEmptyClusters(unittest.TestCase):
    def test_empty_clusters_gives_unknown_for_in_window_release(self):
        releases = [_release("PPI", 0)]
        result = classify_macro_surprise(releases, [])
        self.assertEqual(result[0]["surprise_signal"], "unknown")
        self.assertIsNone(result[0]["headline_evidence"])


if __name__ == "__main__":
    unittest.main()
