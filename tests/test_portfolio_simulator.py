"""Tests for portfolio_simulator.simulate_portfolio()."""

import unittest
from portfolio_simulator import simulate_portfolio


def _event(
    event_id: int,
    tickers: list[dict],
    *,
    confidence: str = "high",
    headline: str = "Test event",
    event_date: str = "2025-01-01",
    revisit_snapshots: list[dict] | None = None,
) -> dict:
    return {
        "id": event_id,
        "headline": headline,
        "event_date": event_date,
        "confidence": confidence,
        "market_tickers": tickers,
        "revisit_snapshots": revisit_snapshots or [],
    }


def _ticker(symbol: str, *, role: str = "beneficiary", return_5d: float | None = 2.0,
            return_1d: float | None = None, return_20d: float | None = None,
            direction_tag: str = "") -> dict:
    return {
        "symbol": symbol,
        "role": role,
        "return_5d": return_5d,
        "return_1d": return_1d,
        "return_20d": return_20d,
        "direction_tag": direction_tag,
    }


class TestSimulatePortfolioBasic(unittest.TestCase):
    def test_empty_events_returns_zero_positions(self):
        result = simulate_portfolio([])
        self.assertEqual(result["summary"]["positions_total"], 0)
        self.assertIsNone(result["summary"]["portfolio_return"])
        self.assertEqual(result["positions"], [])

    def test_single_event_single_ticker(self):
        ev = _event(1, [_ticker("SPY", return_5d=5.0)])
        result = simulate_portfolio([ev])
        self.assertEqual(result["summary"]["positions_total"], 1)
        self.assertEqual(result["summary"]["events_contributing"], 1)
        self.assertAlmostEqual(result["summary"]["portfolio_return"], 5.0, places=2)
        self.assertEqual(result["summary"]["win_rate"], 1.0)

    def test_weight_sums_to_one_for_data_positions(self):
        ev1 = _event(1, [_ticker("SPY", return_5d=3.0), _ticker("QQQ", return_5d=1.0)])
        ev2 = _event(2, [_ticker("GLD", return_5d=2.0)])
        result = simulate_portfolio([ev1, ev2])
        total_weight = sum(p["weight"] for p in result["positions"])
        self.assertAlmostEqual(total_weight, 1.0, places=6)

    def test_loser_excluded_by_default(self):
        ev = _event(1, [
            _ticker("SPY", role="beneficiary", return_5d=3.0),
            _ticker("TLT", role="loser", return_5d=-2.0),
        ])
        result = simulate_portfolio([ev], include_shorts=False)
        symbols = [p["symbol"] for p in result["positions"]]
        self.assertIn("SPY", symbols)
        self.assertNotIn("TLT", symbols)

    def test_loser_short_flips_return(self):
        ev = _event(1, [_ticker("TLT", role="loser", return_5d=-2.0)])
        result = simulate_portfolio([ev], include_shorts=True)
        pos = result["positions"][0]
        self.assertTrue(pos["short"])
        # Short of -2.0 gross → +2.0 portfolio
        self.assertAlmostEqual(pos["portfolio_return"], 2.0, places=4)

    def test_missing_return_excluded_from_weighted_sum(self):
        ev = _event(1, [
            _ticker("SPY", return_5d=4.0),
            _ticker("MISSING", return_5d=None),
        ])
        result = simulate_portfolio([ev])
        with_data = [p for p in result["positions"] if p["portfolio_return"] is not None]
        self.assertEqual(len(with_data), 1)
        # portfolio_return based only on SPY
        self.assertAlmostEqual(result["summary"]["portfolio_return"], 4.0, places=2)

    def test_horizon_1d_uses_return_1d(self):
        ticker = {
            "symbol": "SPY", "role": "beneficiary",
            "return_1d": 1.5, "return_5d": 3.0, "return_20d": 8.0,
            "direction_tag": "",
        }
        ev = _event(1, [ticker])
        result = simulate_portfolio([ev], horizon="1d")
        self.assertAlmostEqual(result["positions"][0]["gross_return"], 1.5, places=4)

    def test_horizon_20d_uses_return_20d(self):
        ticker = {
            "symbol": "SPY", "role": "beneficiary",
            "return_1d": 1.5, "return_5d": 3.0, "return_20d": 8.0,
            "direction_tag": "",
        }
        ev = _event(1, [ticker])
        result = simulate_portfolio([ev], horizon="20d")
        self.assertAlmostEqual(result["positions"][0]["gross_return"], 8.0, places=4)

    def test_invalid_horizon_falls_back_to_5d(self):
        ev = _event(1, [_ticker("SPY", return_5d=2.0)])
        result = simulate_portfolio([ev], horizon="99d")
        self.assertEqual(result["summary"]["horizon"], "5d")


class TestSimulatePortfolioRevisit(unittest.TestCase):
    def test_revisit_snapshot_preferred_over_market_check(self):
        ticker = {"symbol": "SPY", "role": "beneficiary", "return_5d": 3.0, "direction_tag": ""}
        snapshot = {
            "day": 5,
            "captured_at": "2025-01-06T10:00:00",
            "tickers": [{"symbol": "SPY", "return_5d": 6.0}],
        }
        ev = _event(1, [ticker], revisit_snapshots=[snapshot])
        result = simulate_portfolio([ev], horizon="5d")
        pos = result["positions"][0]
        self.assertEqual(pos["return_source"], "revisit")
        self.assertAlmostEqual(pos["gross_return"], 6.0, places=4)

    def test_revisit_nan_falls_back_to_market_check(self):
        ticker = {"symbol": "SPY", "role": "beneficiary", "return_5d": 3.0, "direction_tag": ""}
        snapshot = {
            "day": 5,
            "captured_at": "2025-01-06T10:00:00",
            "tickers": [{"symbol": "SPY", "return_5d": float("nan")}],
        }
        ev = _event(1, [ticker], revisit_snapshots=[snapshot])
        result = simulate_portfolio([ev], horizon="5d")
        pos = result["positions"][0]
        self.assertEqual(pos["return_source"], "market_check")
        self.assertAlmostEqual(pos["gross_return"], 3.0, places=4)

    def test_revisit_wrong_day_ignored(self):
        ticker = {"symbol": "SPY", "role": "beneficiary", "return_5d": 3.0, "direction_tag": ""}
        # Day-1 snapshot cannot satisfy a 5d horizon request
        snapshot = {
            "day": 1,
            "captured_at": "2025-01-02T10:00:00",
            "tickers": [{"symbol": "SPY", "return_1d": 1.0}],
        }
        ev = _event(1, [ticker], revisit_snapshots=[snapshot])
        result = simulate_portfolio([ev], horizon="5d")
        pos = result["positions"][0]
        self.assertEqual(pos["return_source"], "market_check")


class TestSimulatePortfolioWeighting(unittest.TestCase):
    def test_equal_event_weighting(self):
        """Two events with one ticker each → each contributes 50% of portfolio."""
        ev1 = _event(1, [_ticker("SPY", return_5d=10.0)])
        ev2 = _event(2, [_ticker("GLD", return_5d=0.0)])
        result = simulate_portfolio([ev1, ev2])
        # 0.5*10 + 0.5*0 = 5.0
        self.assertAlmostEqual(result["summary"]["portfolio_return"], 5.0, places=4)

    def test_within_event_equal_position_weighting(self):
        """One event with two tickers → each ticker is half the event weight."""
        ev = _event(1, [_ticker("SPY", return_5d=10.0), _ticker("QQQ", return_5d=0.0)])
        result = simulate_portfolio([ev])
        # (10 + 0) / 2 = 5.0
        self.assertAlmostEqual(result["summary"]["portfolio_return"], 5.0, places=4)

    def test_data_coverage_partial(self):
        ev = _event(1, [_ticker("SPY", return_5d=5.0), _ticker("MISS", return_5d=None)])
        result = simulate_portfolio([ev])
        # Only SPY has data; weight = 0.5; coverage = 0.5
        self.assertAlmostEqual(result["summary"]["data_coverage"], 0.5, places=4)


class TestSimulatePortfolioDirectionFilter(unittest.TestCase):
    def test_supporting_filter_excludes_non_supporting(self):
        ev = _event(1, [
            _ticker("SPY", direction_tag="supports_thesis", return_5d=3.0),
            _ticker("QQQ", direction_tag="contradicts_thesis", return_5d=2.0),
            _ticker("GLD", direction_tag="", return_5d=1.0),
        ])
        result = simulate_portfolio([ev], direction_filter="supporting")
        symbols = [p["symbol"] for p in result["positions"]]
        self.assertIn("SPY", symbols)
        self.assertNotIn("QQQ", symbols)
        self.assertNotIn("GLD", symbols)

    def test_all_filter_includes_everything(self):
        ev = _event(1, [
            _ticker("SPY", direction_tag="supports_thesis", return_5d=3.0),
            _ticker("QQQ", direction_tag="contradicts_thesis", return_5d=2.0),
        ])
        result = simulate_portfolio([ev], direction_filter="all")
        self.assertEqual(len(result["positions"]), 2)


class TestSimulatePortfolioWarnings(unittest.TestCase):
    def test_concentration_warning_when_symbol_in_multiple_events(self):
        ev1 = _event(1, [_ticker("SPY", return_5d=2.0)])
        ev2 = _event(2, [_ticker("SPY", return_5d=3.0)])
        result = simulate_portfolio([ev1, ev2])
        conc = [w for w in result["warnings"] if w["type"] == "concentration"]
        self.assertEqual(len(conc), 1)
        self.assertEqual(conc[0]["symbol"], "SPY")
        self.assertEqual(conc[0]["event_count"], 2)

    def test_no_concentration_warning_same_symbol_same_event(self):
        """Duplicate ticker in the same event should NOT trigger concentration."""
        ev = _event(1, [
            _ticker("SPY", return_5d=2.0),
            _ticker("SPY", role="loser", return_5d=-1.0),
        ])
        result = simulate_portfolio([ev], include_shorts=True)
        conc = [w for w in result["warnings"] if w["type"] == "concentration"]
        self.assertEqual(len(conc), 0)

    def test_missing_data_warning(self):
        ev = _event(1, [_ticker("NODATA", return_5d=None)])
        result = simulate_portfolio([ev])
        miss = [w for w in result["warnings"] if w["type"] == "missing_data"]
        self.assertEqual(len(miss), 1)

    def test_low_confidence_warning(self):
        ev = _event(1, [_ticker("SPY", return_5d=2.0)], confidence="low")
        result = simulate_portfolio([ev])
        low = [w for w in result["warnings"] if w["type"] == "low_confidence"]
        self.assertEqual(len(low), 1)

    def test_no_low_confidence_warning_for_high(self):
        ev = _event(1, [_ticker("SPY", return_5d=2.0)], confidence="high")
        result = simulate_portfolio([ev])
        low = [w for w in result["warnings"] if w["type"] == "low_confidence"]
        self.assertEqual(len(low), 0)

    def test_event_with_no_usable_tickers_counted_as_missing(self):
        """Event filtered to zero positions (all losers, no include_shorts)."""
        ev = _event(1, [_ticker("TLT", role="loser", return_5d=-2.0)])
        result = simulate_portfolio([ev], include_shorts=False)
        miss = [w for w in result["warnings"] if w["type"] == "missing_data"]
        self.assertEqual(len(miss), 1)
        # No positions were built
        self.assertEqual(result["summary"]["positions_total"], 0)


class TestSimulatePortfolioReturnShape(unittest.TestCase):
    def test_position_fields_present(self):
        ev = _event(1, [_ticker("SPY", return_5d=2.0)])
        result = simulate_portfolio([ev])
        pos = result["positions"][0]
        for field in ("event_id", "event_headline", "event_date", "event_confidence",
                      "symbol", "role", "direction_tag", "weight",
                      "gross_return", "portfolio_return", "return_source", "short"):
            self.assertIn(field, pos, f"missing field: {field}")

    def test_summary_fields_present(self):
        ev = _event(1, [_ticker("SPY", return_5d=2.0)])
        result = simulate_portfolio([ev])
        for field in ("events_requested", "events_contributing", "events_with_data",
                      "positions_total", "positions_with_data", "portfolio_return",
                      "data_coverage", "win_rate", "horizon", "include_shorts",
                      "direction_filter"):
            self.assertIn(field, result["summary"], f"missing summary field: {field}")

    def test_win_rate_correct(self):
        ev = _event(1, [
            _ticker("SPY", return_5d=2.0),   # winner
            _ticker("QQQ", return_5d=-1.0),  # loser
        ])
        result = simulate_portfolio([ev])
        self.assertAlmostEqual(result["summary"]["win_rate"], 0.5, places=4)


if __name__ == "__main__":
    unittest.main()
