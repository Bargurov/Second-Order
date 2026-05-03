"""Tests for persistence_signal.classify_persistence_signal()."""

import unittest
from datetime import datetime

from persistence_signal import classify_persistence_signal


def _ev(
    persistence: str = "medium",
    event_date: str | None = None,
    timestamp: str = "2025-01-01T00:00:00",
    market_tickers: list | None = None,
    revisit_snapshots: list | None = None,
) -> dict:
    return {
        "persistence": persistence,
        "event_date": event_date,
        "timestamp": timestamp,
        "market_tickers": market_tickers or [],
        "revisit_snapshots": revisit_snapshots or [],
    }


def _ticker(direction_tag: str = "supports_thesis", role: str = "beneficiary") -> dict:
    return {"symbol": "TEST", "direction_tag": direction_tag, "role": role}


def _revisit_ticker(direction: str = "supports", role: str = "beneficiary",
                    return_5d: float | None = None, return_20d: float | None = None,
                    symbol: str = "TEST") -> dict:
    t = {"symbol": symbol, "direction": direction, "role": role}
    if return_5d is not None:
        t["return_5d"] = return_5d
    if return_20d is not None:
        t["return_20d"] = return_20d
    return t


def _snap(day: int, tickers: list, captured_at: str = "2025-01-10T00:00:00") -> dict:
    return {"day": day, "captured_at": captured_at, "tickers": tickers}


NOW = datetime(2025, 3, 1)


class TestHorizon(unittest.TestCase):
    def test_transient_horizon(self):
        ev = _ev("transient", event_date="2025-02-24")  # 5 days before NOW
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["horizon_days"], 5)

    def test_medium_horizon(self):
        ev = _ev("medium", event_date="2025-02-25")
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["horizon_days"], 20)

    def test_structural_horizon(self):
        ev = _ev("structural", event_date="2025-02-25")
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["horizon_days"], 90)

    def test_unknown_persistence_defaults_30d(self):
        ev = _ev("cyclical", event_date="2025-02-25")
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["horizon_days"], 30)


class TestResolvedPastHorizon(unittest.TestCase):
    def test_past_medium_horizon_no_revisit(self):
        # medium = 20d; 25 days ago
        ev = _ev("medium", event_date="2025-02-04")  # 25d before Mar 1
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "resolved")

    def test_past_horizon_with_contradicting_revisit(self):
        snap = _snap(20, [
            _revisit_ticker("contradicts", "beneficiary"),
            _revisit_ticker("contradicts", "beneficiary"),
        ])
        ev = _ev("medium", event_date="2025-02-04", revisit_snapshots=[snap])
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "resolved")
        self.assertIn("Contradicted", result["label"])

    def test_past_horizon_with_supporting_revisit(self):
        snap = _snap(20, [_revisit_ticker("supports", "beneficiary")])
        ev = _ev("medium", event_date="2025-02-04", revisit_snapshots=[snap])
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["label"], "Resolved")


class TestWatching(unittest.TestCase):
    def test_young_event_no_revisit(self):
        # 1 day ago
        ev = _ev("medium", event_date="2025-02-28")
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "watching")

    def test_watching_within_3d_threshold(self):
        ev = _ev("medium", event_date="2025-02-27")  # 2 days ago
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "watching")


class TestActiveWithDirectionData(unittest.TestCase):
    def test_high_support_ratio_active(self):
        tickers = [
            _ticker("supports_thesis"),
            _ticker("supports_thesis"),
            _ticker("supports_thesis"),
        ]
        ev = _ev("medium", event_date="2025-02-15", market_tickers=tickers)
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "active")

    def test_low_support_ratio_fading(self):
        tickers = [
            _ticker("contradicts_thesis"),
            _ticker("contradicts_thesis"),
            _ticker("contradicts_thesis"),
        ]
        ev = _ev("medium", event_date="2025-02-15", market_tickers=tickers)
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "fading")

    def test_mixed_support_fading(self):
        tickers = [
            _ticker("supports_thesis"),
            _ticker("contradicts_thesis"),
        ]
        ev = _ev("medium", event_date="2025-02-15", market_tickers=tickers)
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "fading")

    def test_no_direction_data_unvalidated(self):
        # Tickers present but no direction tags
        tickers = [{"symbol": "XYZ", "direction_tag": None}]
        ev = _ev("medium", event_date="2025-02-15", market_tickers=tickers)
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "watching")
        self.assertIn("Unvalidated", result["label"])


class TestRevisitOverridesInitialTickers(unittest.TestCase):
    def test_revisit_data_preferred_over_initial(self):
        # Initial tickers say "supports" but revisit says "contradicts"
        initial = [_ticker("supports_thesis")]
        snap = _snap(5, [_revisit_ticker("contradicts", "beneficiary")])
        ev = _ev("medium", event_date="2025-02-15",
                 market_tickers=initial, revisit_snapshots=[snap])
        result = classify_persistence_signal(ev, now=NOW)
        # Revisit has 1 contradicting → support_ratio 0 → fading
        self.assertEqual(result["status"], "fading")
        self.assertIn("day-5 revisit", result["evidence"])


class TestTrajectory(unittest.TestCase):
    def test_building_momentum(self):
        # day-5 return_5d=2, day-20 return_20d=4 → delta +2 → building
        snap5 = _snap(5, [_revisit_ticker("supports", "beneficiary",
                                          return_5d=2.0, symbol="A")])
        snap20 = _snap(20, [_revisit_ticker("supports", "beneficiary",
                                            return_20d=4.0, symbol="A")])
        ev = _ev("medium", event_date="2025-02-15",  # 14d < 20d horizon
                 revisit_snapshots=[snap5, snap20])
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "active")
        self.assertIn("\u2191", result["label"])  # "Active ↑"

    def test_fading_trajectory_overrides_high_ratio(self):
        # Support ratio is high (2/2 = 1.0) but trajectory is fading
        snap5 = _snap(5, [
            _revisit_ticker("supports", "beneficiary", return_5d=3.0, symbol="A"),
            _revisit_ticker("supports", "beneficiary", return_5d=2.0, symbol="B"),
        ])
        snap20 = _snap(20, [
            _revisit_ticker("supports", "beneficiary", return_20d=0.5, symbol="A"),
            _revisit_ticker("supports", "beneficiary", return_20d=0.0, symbol="B"),
        ])
        # delta A: 0.5-3.0 = -2.5, delta B: 0-2.0 = -2.0 → avg -2.25 → fading
        ev = _ev("medium", event_date="2025-02-15",  # 14d < 20d horizon
                 revisit_snapshots=[snap5, snap20])
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "fading")

    def test_trajectory_unknown_without_both_snapshots(self):
        # Only day-5 snapshot, no day-20 → trajectory unknown → no ↑ label
        snap5 = _snap(5, [_revisit_ticker("supports", "beneficiary",
                                          return_5d=3.0, symbol="A")])
        ev = _ev("medium", event_date="2025-02-15",
                 revisit_snapshots=[snap5])
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["status"], "active")
        self.assertNotIn("\u2191", result["label"])


class TestOutputShape(unittest.TestCase):
    def test_all_fields_present(self):
        ev = _ev("medium", event_date="2025-02-15")
        result = classify_persistence_signal(ev, now=NOW)
        for key in ("status", "label", "evidence", "horizon_days", "days_elapsed"):
            self.assertIn(key, result)

    def test_days_elapsed_computed(self):
        ev = _ev("medium", event_date="2025-02-20")  # 9 days before NOW
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["days_elapsed"], 9)

    def test_falls_back_to_timestamp_when_no_event_date(self):
        ev = _ev("medium", event_date=None, timestamp="2025-02-20T00:00:00")
        result = classify_persistence_signal(ev, now=NOW)
        self.assertEqual(result["days_elapsed"], 9)


if __name__ == "__main__":
    unittest.main()
