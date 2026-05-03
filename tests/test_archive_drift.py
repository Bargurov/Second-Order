"""Tests for archive_drift — theme trend + regime drift windows."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from archive_drift import (
    DEFAULT_WINDOWS_DAYS,
    REGIME_AXES,
    _TREND_LARGE,
    _TREND_MEDIUM,
    _TREND_SMALL,
    _WINDOW_THIN_SIZE,
    build_archive_drift,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

NOW = date(2026, 4, 19)


def _ev(
    eid: int,
    days_ago: int,
    family: str = "tariff",
    regime: dict | None = None,
) -> dict:
    d = (NOW - timedelta(days=days_ago)).isoformat()
    ev = {
        "id": eid,
        "headline": f"Headline {eid}",
        "event_date": d,
        "mechanism_family": family,
    }
    if regime is not None:
        ev["regime_snapshot"] = regime
    return ev


def _axis_regime(axis: str, value: str) -> dict:
    return {axis: value}


# ---------------------------------------------------------------------------
# Shape + contract
# ---------------------------------------------------------------------------

class TestShape(unittest.TestCase):
    def test_empty_input_safe(self):
        r = build_archive_drift([], now=NOW)
        self.assertFalse(r["available"])
        self.assertEqual(r["windows"][0]["size"], 0)
        self.assertEqual(r["theme_trends"], [])
        # Regime drift always returns one entry per axis so the UI shape
        # is stable; every entry tags as "unavailable" when there's no
        # data to compare.
        self.assertEqual(len(r["regime_drift"]), len(REGIME_AXES))
        self.assertTrue(all(d["direction"] == "unavailable" for d in r["regime_drift"]))

    def test_none_input_safe(self):
        r = build_archive_drift(None, now=NOW)
        self.assertFalse(r["available"])

    def test_output_shape(self):
        evs = [_ev(1, 2, "tariff")]
        r = build_archive_drift(evs, now=NOW)
        for k in [
            "available", "anchor_date", "windows", "theme_trends",
            "regime_drift", "confidence_basis", "summary",
        ]:
            self.assertIn(k, r)

    def test_constants_pinned(self):
        self.assertEqual(DEFAULT_WINDOWS_DAYS, (30, 90, 180))
        self.assertGreater(_TREND_LARGE, _TREND_MEDIUM)
        self.assertGreater(_TREND_MEDIUM, _TREND_SMALL)
        self.assertEqual(_WINDOW_THIN_SIZE, 3)

    def test_regime_axes_pinned(self):
        for axis in ("inflation", "policy_stance", "fx", "growth_stress",
                     "credit", "curve_shape", "inflation_path"):
            self.assertIn(axis, REGIME_AXES)


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------

class TestWindowing(unittest.TestCase):
    def test_recent_event_in_first_window(self):
        evs = [_ev(1, 5, "tariff")]
        r = build_archive_drift(evs, now=NOW)
        self.assertEqual(r["windows"][0]["size"], 1)
        self.assertEqual(r["windows"][1]["size"], 0)

    def test_older_event_falls_into_prior_window(self):
        evs = [_ev(1, 60, "tariff")]
        r = build_archive_drift(evs, now=NOW)
        self.assertEqual(r["windows"][0]["size"], 0)
        self.assertEqual(r["windows"][1]["size"], 1)

    def test_beyond_last_window_dropped(self):
        evs = [_ev(1, 400, "tariff")]
        r = build_archive_drift(evs, now=NOW)
        self.assertTrue(all(w["size"] == 0 for w in r["windows"]))

    def test_event_without_date_skipped(self):
        evs = [{"id": 1, "mechanism_family": "tariff"}]
        r = build_archive_drift(evs, now=NOW)
        self.assertTrue(all(w["size"] == 0 for w in r["windows"]))

    def test_timestamp_fallback_used_when_event_date_missing(self):
        evs = [{
            "id": 1,
            "timestamp": (NOW - timedelta(days=5)).isoformat() + "T12:00:00Z",
            "mechanism_family": "tariff",
        }]
        r = build_archive_drift(evs, now=NOW)
        self.assertEqual(r["windows"][0]["size"], 1)

    def test_non_dict_event_skipped(self):
        r = build_archive_drift(["garbage", None, 42], now=NOW)
        self.assertFalse(r["available"])

    def test_custom_windows_applied(self):
        evs = [_ev(1, 10, "tariff"), _ev(2, 50, "tariff")]
        r = build_archive_drift(evs, now=NOW, windows_days=(20, 100))
        self.assertEqual(r["windows"][0]["size"], 1)
        self.assertEqual(r["windows"][1]["size"], 1)


# ---------------------------------------------------------------------------
# Theme trends
# ---------------------------------------------------------------------------

class TestThemeTrends(unittest.TestCase):
    def test_rising_theme_tagged_up(self):
        # Recent: all tariff; Prior: all sanction → tariff up, sanction down.
        evs = [_ev(i, 5, "tariff") for i in range(1, 5)] + [
            _ev(i, 60, "sanction") for i in range(100, 104)
        ]
        r = build_archive_drift(evs, now=NOW)
        trends = {t["family"]: t for t in r["theme_trends"]}
        self.assertEqual(trends["tariff"]["direction"], "up")
        self.assertEqual(trends["tariff"]["magnitude"], "large")
        self.assertEqual(trends["sanction"]["direction"], "down")
        self.assertEqual(trends["sanction"]["magnitude"], "large")

    def test_flat_theme_tagged_noise(self):
        evs = [_ev(i, 5, "tariff") for i in range(1, 5)] + [
            _ev(i, 60, "tariff") for i in range(100, 104)
        ]
        r = build_archive_drift(evs, now=NOW)
        trends = {t["family"]: t for t in r["theme_trends"]}
        # Both windows are 100% tariff → delta = 0.
        self.assertEqual(trends["tariff"]["direction"], "flat")
        self.assertEqual(trends["tariff"]["magnitude"], "noise")

    def test_none_family_excluded(self):
        evs = [_ev(i, 5, "none") for i in range(1, 4)]
        r = build_archive_drift(evs, now=NOW)
        self.assertTrue(all(t["family"] != "none" for t in r["theme_trends"]))

    def test_trends_sorted_by_magnitude(self):
        evs = [_ev(i, 5, "tariff") for i in range(1, 5)] + [
            _ev(i, 5, "sanction") for i in range(10, 12)
        ] + [_ev(i, 60, "sanction") for i in range(100, 105)]
        r = build_archive_drift(evs, now=NOW)
        # Biggest |delta| first — deterministic.
        deltas = [abs(t["delta"]) for t in r["theme_trends"]]
        self.assertEqual(deltas, sorted(deltas, reverse=True))


# ---------------------------------------------------------------------------
# Regime drift
# ---------------------------------------------------------------------------

class TestRegimeDrift(unittest.TestCase):
    def test_regime_shift_detected(self):
        evs = (
            [_ev(i, 5, "tariff", regime=_axis_regime("inflation", "hot"))
             for i in range(1, 5)]
            + [_ev(i, 60, "tariff", regime=_axis_regime("inflation", "cool"))
               for i in range(100, 104)]
        )
        r = build_archive_drift(evs, now=NOW)
        drift = {d["axis"]: d for d in r["regime_drift"]}
        self.assertEqual(drift["inflation"]["direction"], "shifted")
        self.assertEqual(drift["inflation"]["recent"], "hot")
        self.assertEqual(drift["inflation"]["prior"], "cool")

    def test_regime_stable_when_unchanged(self):
        evs = (
            [_ev(i, 5, "tariff", regime=_axis_regime("inflation", "hot"))
             for i in range(1, 5)]
            + [_ev(i, 60, "tariff", regime=_axis_regime("inflation", "hot"))
               for i in range(100, 104)]
        )
        r = build_archive_drift(evs, now=NOW)
        drift = {d["axis"]: d for d in r["regime_drift"]}
        self.assertEqual(drift["inflation"]["direction"], "stable")

    def test_regime_unavailable_when_no_data(self):
        evs = [_ev(i, 5, "tariff") for i in range(1, 4)]
        r = build_archive_drift(evs, now=NOW)
        drift = {d["axis"]: d for d in r["regime_drift"]}
        for axis in REGIME_AXES:
            self.assertEqual(drift[axis]["direction"], "unavailable")

    def test_multiple_axes_surfaced(self):
        regime = {
            "inflation": "hot",
            "policy_stance": "hawkish",
            "credit": "risk_off",
        }
        old_regime = {
            "inflation": "cool",
            "policy_stance": "dovish",
            "credit": "risk_on",
        }
        evs = (
            [_ev(i, 5, "tariff", regime=regime) for i in range(1, 5)]
            + [_ev(i, 60, "tariff", regime=old_regime) for i in range(100, 104)]
        )
        r = build_archive_drift(evs, now=NOW)
        drift = {d["axis"]: d for d in r["regime_drift"]}
        for axis in ("inflation", "policy_stance", "credit"):
            self.assertEqual(drift[axis]["direction"], "shifted")
        # Axes not present in either window are "unavailable".
        self.assertEqual(drift["fx"]["direction"], "unavailable")


# ---------------------------------------------------------------------------
# Confidence basis + summary
# ---------------------------------------------------------------------------

class TestConfidenceAndSummary(unittest.TestCase):
    def test_thin_when_windows_small(self):
        evs = [_ev(1, 5, "tariff")]
        r = build_archive_drift(evs, now=NOW)
        self.assertEqual(r["confidence_basis"], "thin")

    def test_medium_when_both_windows_have_minimum(self):
        evs = (
            [_ev(i, 5, "tariff") for i in range(1, 5)]
            + [_ev(i, 60, "sanction") for i in range(100, 104)]
        )
        r = build_archive_drift(evs, now=NOW)
        self.assertEqual(r["confidence_basis"], "medium")

    def test_deep_when_both_windows_large(self):
        evs = (
            [_ev(i, 5, "tariff") for i in range(1, 15)]
            + [_ev(i, 60, "sanction") for i in range(100, 115)]
        )
        r = build_archive_drift(evs, now=NOW)
        self.assertEqual(r["confidence_basis"], "deep")

    def test_summary_mentions_rising_themes(self):
        evs = (
            [_ev(i, 5, "tariff") for i in range(1, 6)]
            + [_ev(i, 60, "sanction") for i in range(100, 105)]
        )
        r = build_archive_drift(evs, now=NOW)
        self.assertIn("tariff", r["summary"])

    def test_summary_mentions_regime_shift(self):
        evs = (
            [_ev(i, 5, "tariff", regime=_axis_regime("inflation", "hot"))
             for i in range(1, 6)]
            + [_ev(i, 60, "tariff", regime=_axis_regime("inflation", "cool"))
               for i in range(100, 105)]
        )
        r = build_archive_drift(evs, now=NOW)
        self.assertIn("inflation", r["summary"].lower())

    def test_summary_flags_quiet_archive(self):
        evs = (
            [_ev(i, 5, "tariff") for i in range(1, 6)]
            + [_ev(i, 60, "tariff") for i in range(100, 105)]
        )
        r = build_archive_drift(evs, now=NOW)
        self.assertIn("quiet", r["summary"].lower())

    def test_summary_flags_empty_archive(self):
        r = build_archive_drift([], now=NOW)
        self.assertIn("nothing", r["summary"].lower())


if __name__ == "__main__":
    unittest.main()
