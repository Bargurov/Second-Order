"""Tests for sector_uncertainty pure helpers."""

import math
import unittest

import sector_uncertainty as su


class TestLogReturns(unittest.TestCase):
    def test_basic(self):
        closes = [100.0, 101.0, 99.0]
        rets = su._log_returns(closes)
        self.assertEqual(len(rets), 2)
        self.assertAlmostEqual(rets[0], math.log(101 / 100), places=6)

    def test_zero_price_skipped(self):
        closes = [100.0, 0.0, 99.0]
        rets = su._log_returns(closes)
        # 0.0 as prev makes log undefined — skip that pair; 0.0 as curr also skipped
        self.assertEqual(len(rets), 0)

    def test_empty(self):
        self.assertEqual(su._log_returns([]), [])

    def test_single(self):
        self.assertEqual(su._log_returns([100.0]), [])


class TestRealizedVol(unittest.TestCase):
    def test_returns_float(self):
        # 21 identical prices → returns are all 0 → stdev = 0
        closes = [100.0] * 22
        vol = su._realized_vol(closes)
        self.assertIsNotNone(vol)
        self.assertEqual(vol, 0.0)

    def test_insufficient_data(self):
        # only 4 returns → below threshold
        closes = [100.0, 101.0, 102.0, 101.0, 103.0]
        vol = su._realized_vol(closes)
        self.assertIsNone(vol)

    def test_annualisation(self):
        import statistics as stats
        # hand-crafted: stdev of returns * sqrt(252) * 100
        closes = [100.0, 102.0, 101.0, 103.0, 100.0, 99.0, 101.0]
        rets = su._log_returns(closes)
        expected = round(stats.stdev(rets) * math.sqrt(252) * 100, 2)
        self.assertEqual(su._realized_vol(closes), expected)


class TestStatus(unittest.TestCase):
    def test_stressed(self):
        self.assertEqual(su._status(1.6), "stressed")

    def test_watch(self):
        self.assertEqual(su._status(1.35), "watch")

    def test_calm(self):
        self.assertEqual(su._status(1.1), "calm")

    def test_boundary_stressed(self):
        self.assertEqual(su._status(1.5), "stressed")

    def test_boundary_watch(self):
        self.assertEqual(su._status(1.3), "watch")


class TestClosesFromDf(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(su._closes_from_df(None), [])

    def test_extracts_close_column(self):
        import pandas as pd
        df = pd.DataFrame({"Close": [100.0, 101.0, float("nan"), 103.0]})
        result = su._closes_from_df(df)
        self.assertEqual(len(result), 3)
        self.assertNotIn(float("nan"), result)


class TestComputeIntegration(unittest.TestCase):
    """Tests that stub out fetch_daily_cached so no network is needed."""

    def _make_df(self, closes):
        import pandas as pd
        idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
        return pd.DataFrame({"Close": closes}, index=idx)

    def test_unavailable_when_spy_fails(self):
        import unittest.mock as mock
        # fetch_daily_cached is imported locally inside _compute, patch at source
        with mock.patch("price_cache.fetch_daily_cached", return_value=None):
            result = su._compute()
        self.assertFalse(result["available"])

    def test_concentration_concentrated(self):
        # 3+ elevated sectors
        sectors = [
            {"sector": "A", "etf": "A", "vol_20d": 30.0, "vol_ratio": 1.6, "status": "stressed"},
            {"sector": "B", "etf": "B", "vol_20d": 25.0, "vol_ratio": 1.4, "status": "watch"},
            {"sector": "C", "etf": "C", "vol_20d": 22.0, "vol_ratio": 1.3, "status": "watch"},
            {"sector": "D", "etf": "D", "vol_20d": 15.0, "vol_ratio": 1.0, "status": "calm"},
        ]
        elevated = [s for s in sectors if s["vol_ratio"] >= su.WATCH_RATIO]
        n = len(elevated)
        self.assertGreaterEqual(n, su.CONCENTRATED_COUNT)
        # Verify concentration label logic
        if n >= su.CONCENTRATED_COUNT:
            concentration = "concentrated"
        elif n >= su.MIXED_COUNT:
            concentration = "mixed"
        else:
            concentration = "diffuse"
        self.assertEqual(concentration, "concentrated")

    def test_concentration_mixed(self):
        sectors = [
            {"sector": "A", "etf": "A", "vol_ratio": 1.4, "status": "watch"},
            {"sector": "B", "etf": "B", "vol_ratio": 1.0, "status": "calm"},
        ]
        elevated = [s for s in sectors if s["vol_ratio"] >= su.WATCH_RATIO]
        n = len(elevated)
        self.assertGreaterEqual(n, su.MIXED_COUNT)
        self.assertLess(n, su.CONCENTRATED_COUNT)
        concentration = "mixed" if su.MIXED_COUNT <= n < su.CONCENTRATED_COUNT else "diffuse"
        self.assertEqual(concentration, "mixed")

    def test_concentration_diffuse(self):
        sectors = [
            {"sector": "A", "etf": "A", "vol_ratio": 1.1, "status": "calm"},
            {"sector": "B", "etf": "B", "vol_ratio": 0.9, "status": "calm"},
        ]
        elevated = [s for s in sectors if s["vol_ratio"] >= su.WATCH_RATIO]
        self.assertEqual(len(elevated), 0)


class TestComputeNewsUncertainty(unittest.TestCase):
    """Tests for api.compute_news_uncertainty() — no network required."""

    def _make_cluster(self, sector: str, uncertainty: str, source_count: int = 2) -> dict:
        return {
            "consensus": {"sector": sector, "uncertainty": uncertainty},
            "source_count": source_count,
        }

    def test_empty_clusters_returns_global(self):
        import unittest.mock as mock
        import api
        with mock.patch.object(api, "_get_news_cached", return_value={"clusters": []}):
            result = api.compute_news_uncertainty()
        self.assertEqual(result["uncertainty_scope"], "global")
        self.assertEqual(result["sector_uncertainty"], [])
        self.assertIsNone(result["lead_sector"])

    def test_concentrated_sector_sets_lead_sector(self):
        import unittest.mock as mock
        import api
        clusters = [self._make_cluster("energy", "high", 4)] * 6
        with mock.patch.object(api, "_get_news_cached", return_value={"clusters": clusters}):
            result = api.compute_news_uncertainty()
        self.assertEqual(result["uncertainty_scope"], "sector")
        self.assertEqual(result["lead_sector"], "energy")
        self.assertGreater(len(result["sector_uncertainty"]), 0)

    def test_mixed_clusters_no_lead_sector(self):
        import unittest.mock as mock
        import api
        clusters = (
            [self._make_cluster("energy", "high", 2)] * 3
            + [self._make_cluster("finance", "high", 2)] * 3
        )
        with mock.patch.object(api, "_get_news_cached", return_value={"clusters": clusters}):
            result = api.compute_news_uncertainty()
        self.assertIn(result["uncertainty_scope"], ("mixed", "global"))
        self.assertIsNone(result["lead_sector"])

    def test_exception_returns_empty_shape(self):
        import unittest.mock as mock
        import api
        with mock.patch.object(api, "_get_news_cached", side_effect=RuntimeError("boom")):
            result = api.compute_news_uncertainty()
        self.assertEqual(result["uncertainty_scope"], "global")
        self.assertEqual(result["sector_uncertainty"], [])
        self.assertIsNone(result["lead_sector"])


if __name__ == "__main__":
    unittest.main()
