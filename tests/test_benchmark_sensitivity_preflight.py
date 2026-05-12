"""Tests for ``scripts/benchmark_sensitivity_preflight.py``.

Pin the contract:

* The preflight reads archive state through ONE patchable seam
  (``_load_archive_state``) so unit tests can drive it with synthetic
  payloads — no DB is ever touched on the test path.
* Top-level JSON keys: ``ok``, ``checked_events``, ``ready_count``,
  ``blocked_count``, ``rows``, ``recommended_next_action``.
* Per-row keys (exactly 11): ``event_id``, ``primary_ticker``,
  ``benchmark_ticker``, ``event_date``, ``required_horizons``,
  ``primary_cache_available``, ``benchmark_cache_available``,
  ``missing_primary_ranges``, ``missing_benchmark_ranges``,
  ``can_run_sensitivity``, ``blocker_reason``.
* Default event ids are ``60`` and ``73``.
* Default benchmark is ``XLE``.
* Default horizons are ``(1, 5, 20)`` business days.
* Default estimation window is ``60`` distinct pre-event dates.
* Read-only: default run does not import yfinance / market_check /
  market_data / price_cache / api / fastapi / routes.*.
* Conservative wording — banned tokens in
  ``recommended_next_action`` and ``blocker_reason``: ``delete``,
  ``auto-correct``, ``auto fix``, ``automatic``, ``assign``,
  ``fix the``, ``replace``, ``correct``.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, timedelta
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import benchmark_sensitivity_preflight as cli  # noqa: E402


_TOP_LEVEL_KEYS = (
    "ok",
    "checked_events",
    "ready_count",
    "blocked_count",
    "rows",
    "recommended_next_action",
)


_PER_ROW_KEYS = (
    "event_id",
    "primary_ticker",
    "benchmark_ticker",
    "event_date",
    "required_horizons",
    "primary_cache_available",
    "benchmark_cache_available",
    "missing_primary_ranges",
    "missing_benchmark_ranges",
    "can_run_sensitivity",
    "blocker_reason",
)


_BANNED_WORDS = (
    "delete",
    "auto-correct",
    "auto fix",
    "automatic",
    "assign",
    "fix the",
    "replace",
    "correct",
)


# ---------------------------------------------------------------------------
# Synthetic state helpers
# ---------------------------------------------------------------------------


def _bd_dates(start: date, count: int) -> list[str]:
    """Return ``count`` consecutive business days starting at ``start``
    (or the next weekday if ``start`` is a weekend)."""
    out: list[str] = []
    cur = start
    one = timedelta(days=1)
    while cur.weekday() >= 5:
        cur = cur + one
    while len(out) < count:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur = cur + one
    return out


def _trading_days_inclusive(start: date, end: date) -> list[str]:
    """Trading-day ISO list, holiday-aware via the module's own set.

    Skips weekends and any date in ``cli._MARKET_HOLIDAYS`` so the test
    cache exactly mirrors what a real price provider would return: a
    NYSE-closed date such as ``2026-01-01`` is omitted entirely.
    """
    out: list[str] = []
    cur = start
    one = timedelta(days=1)
    holidays = getattr(cli, "_MARKET_HOLIDAYS", frozenset())
    while cur <= end:
        if cur.weekday() < 5 and cur not in holidays:
            out.append(cur.isoformat())
        cur = cur + one
    return out


def _full_cache_for(
    event_date: date, *,
    pre_count: int = 60,
    forward_count: int = 30,
) -> list[str]:
    """A cache that satisfies estimation-window AND forward-horizon
    checks for the given event_date.

    ``pre_count`` distinct *trading* days strictly before ``event_date``
    + ``forward_count`` trading days from ``event_date`` onward.  Trading
    days skip both weekends and known US market holidays, mirroring
    what a real ``price_cache`` populated by a provider fetch contains.
    """
    holidays = getattr(cli, "_MARKET_HOLIDAYS", frozenset())
    one = timedelta(days=1)

    # Walk back ``pre_count`` trading days.
    pre: list[str] = []
    cur = event_date
    while len(pre) < pre_count:
        cur = cur - one
        if cur.weekday() < 5 and cur not in holidays:
            pre.append(cur.isoformat())
    pre.reverse()

    # Walk forward ``forward_count`` trading days starting at event_date
    # (or the next trading day if event_date itself is a weekend / holiday).
    forward: list[str] = []
    cur = event_date
    while len(forward) < forward_count:
        if cur.weekday() < 5 and cur not in holidays:
            forward.append(cur.isoformat())
        cur = cur + one
    return sorted(set(pre + forward))


def _state(
    *,
    events: dict[int, dict[str, Any]],
    cache:  dict[str, list[str]],
) -> dict[str, Any]:
    return {"events": events, "cache": cache}


def _patch_loader(state: dict[str, Any]):
    return patch.object(cli, "_load_archive_state", return_value=state)


def _run(*, state: dict[str, Any], **kwargs) -> dict[str, Any]:
    with _patch_loader(state):
        return cli.summarize_benchmark_sensitivity_preflight(**kwargs)


def _run_cli(
    argv: list[str], *, state: dict[str, Any],
) -> tuple[int, str]:
    out = StringIO()
    with _patch_loader(state):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Top-level contract
# ---------------------------------------------------------------------------


class TestTopLevelContract(unittest.TestCase):
    def test_top_level_keys_present(self) -> None:
        result = _run(state=_state(events={}, cache={}), event_ids=())
        for k in _TOP_LEVEL_KEYS:
            self.assertIn(k, result)

    def test_default_event_ids_are_60_and_73(self) -> None:
        self.assertEqual(cli._DEFAULT_EVENT_IDS, (60, 73))

    def test_default_benchmark_is_xle(self) -> None:
        self.assertEqual(cli._DEFAULT_BENCHMARK, "XLE")

    def test_ok_true_when_no_internal_errors(self) -> None:
        result = _run(state=_state(events={}, cache={}), event_ids=())
        self.assertTrue(result["ok"])

    def test_ready_plus_blocked_equals_checked(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={
                60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"},
                73: {"event_date": "2026-04-06",        "primary_ticker": "XOM"},
            },
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=80, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60, 73), benchmark="XLE")
        self.assertEqual(
            result["ready_count"] + result["blocked_count"],
            result["checked_events"],
        )


# ---------------------------------------------------------------------------
# Per-row schema
# ---------------------------------------------------------------------------


class TestPerRowSchema(unittest.TestCase):
    def test_each_row_has_exactly_eleven_keys(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date),
                "XLE": _full_cache_for(ev_date),
            },
        )
        result = _run(state=state, event_ids=(60,))
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(set(result["rows"][0].keys()), set(_PER_ROW_KEYS))

    def test_required_horizons_carry_through(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={"XOM": _full_cache_for(ev_date), "XLE": _full_cache_for(ev_date)},
        )
        result = _run(
            state=state, event_ids=(60,),
            horizons=(1, 5, 20), benchmark="XLE",
        )
        self.assertEqual(result["rows"][0]["required_horizons"], [1, 5, 20])

    def test_benchmark_ticker_set_per_row(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={"XOM": _full_cache_for(ev_date), "SPY": _full_cache_for(ev_date)},
        )
        result = _run(state=state, event_ids=(60,), benchmark="SPY")
        self.assertEqual(result["rows"][0]["benchmark_ticker"], "SPY")

    def test_benchmark_lowercase_input_normalized(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={"XOM": _full_cache_for(ev_date), "XLE": _full_cache_for(ev_date)},
        )
        result = _run(state=state, event_ids=(60,), benchmark="xle")
        self.assertEqual(result["rows"][0]["benchmark_ticker"], "XLE")

    def test_event_date_carries_through(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": "2026-04-08", "primary_ticker": "XOM"}},
            cache={"XOM": _full_cache_for(ev_date), "XLE": _full_cache_for(ev_date)},
        )
        result = _run(state=state, event_ids=(60,))
        self.assertEqual(result["rows"][0]["event_date"], "2026-04-08")


# ---------------------------------------------------------------------------
# Ready-state path
# ---------------------------------------------------------------------------


class TestReadyState(unittest.TestCase):
    def test_full_cache_yields_can_run_true(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=80, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertTrue(row["primary_cache_available"])
        self.assertTrue(row["benchmark_cache_available"])
        self.assertTrue(row["can_run_sensitivity"])
        self.assertEqual(row["missing_primary_ranges"], [])
        self.assertEqual(row["missing_benchmark_ranges"], [])
        self.assertEqual(row["blocker_reason"], "ready")

    def test_ready_count_increments_for_ready_rows(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={
                60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"},
                73: {"event_date": "2026-04-06",        "primary_ticker": "XOM"},
            },
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=80, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60, 73), benchmark="XLE")
        self.assertEqual(result["ready_count"], 2)
        self.assertEqual(result["blocked_count"], 0)


# ---------------------------------------------------------------------------
# Estimation-window short
# ---------------------------------------------------------------------------


class TestEstimationWindowShort(unittest.TestCase):
    def test_xle_estimation_short_blocks_event(self) -> None:
        # Event 60 (2026-04-08) — XLE has only 58 distinct pre-event
        # business days, two short of the 60 required.  Mirror the live
        # archive state observed for the manual-review backlog.
        ev_date = date(2026, 4, 8)
        # Pre-event cache: 58 dates strictly before event_date.
        xle_pre = _full_cache_for(ev_date, pre_count=58, forward_count=30)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": xle_pre,
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertTrue(row["primary_cache_available"])
        self.assertFalse(row["benchmark_cache_available"])
        self.assertFalse(row["can_run_sensitivity"])
        # Should surface a single estimation_window_short range.
        reasons = {r["reason"] for r in row["missing_benchmark_ranges"]}
        self.assertIn("estimation_window_short", reasons)
        # Range must precede cache_min for the benchmark.
        rg = next(
            r for r in row["missing_benchmark_ranges"]
            if r["reason"] == "estimation_window_short"
        )
        cache_min = min(xle_pre)
        self.assertLess(rg["start"], cache_min)
        self.assertLess(rg["end"],   cache_min)
        self.assertLessEqual(rg["start"], rg["end"])

    def test_estimation_short_range_keys_are_iso(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=58, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        rg = row["missing_benchmark_ranges"][0]
        self.assertEqual(set(rg.keys()), {"start", "end", "reason"})
        # ISO YYYY-MM-DD parses cleanly.
        date.fromisoformat(rg["start"])
        date.fromisoformat(rg["end"])

    def test_blocker_reason_names_benchmark_and_estimation(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=58, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        reason = result["rows"][0]["blocker_reason"]
        self.assertIn("XLE",                     reason)
        self.assertIn("estimation_window_short", reason)


# ---------------------------------------------------------------------------
# Forward-horizon gap
# ---------------------------------------------------------------------------


class TestForwardHorizonGap(unittest.TestCase):
    def test_forward_gap_blocks_event(self) -> None:
        ev_date = date(2026, 4, 8)
        # XLE has plenty of pre-event coverage but stops only 5
        # business days after the event — short of 20bd.
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=80, forward_count=6),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["benchmark_cache_available"])
        reasons = {r["reason"] for r in row["missing_benchmark_ranges"]}
        self.assertIn("forward_horizon_gap", reasons)

    def test_forward_gap_range_starts_after_cache_max(self) -> None:
        ev_date = date(2026, 4, 8)
        xle_cache = _full_cache_for(ev_date, pre_count=80, forward_count=6)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": xle_cache,
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        rg = next(
            r for r in result["rows"][0]["missing_benchmark_ranges"]
            if r["reason"] == "forward_horizon_gap"
        )
        cache_max = max(xle_cache)
        self.assertGreater(rg["start"], cache_max)


# ---------------------------------------------------------------------------
# Empty cache
# ---------------------------------------------------------------------------


class TestEmptyCache(unittest.TestCase):
    def test_no_cache_for_benchmark_emits_no_cache_range(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date),
                # XLE: no rows.
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["benchmark_cache_available"])
        self.assertEqual(len(row["missing_benchmark_ranges"]), 1)
        rg = row["missing_benchmark_ranges"][0]
        self.assertEqual(rg["reason"], "no_cache_for_ticker")
        self.assertLess(rg["start"], rg["end"])

    def test_no_cache_for_primary_blocks_event(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XLE": _full_cache_for(ev_date),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["primary_cache_available"])
        self.assertFalse(row["can_run_sensitivity"])
        self.assertEqual(len(row["missing_primary_ranges"]), 1)
        self.assertEqual(
            row["missing_primary_ranges"][0]["reason"], "no_cache_for_ticker")


# ---------------------------------------------------------------------------
# Degraded inputs
# ---------------------------------------------------------------------------


class TestDegradedInputs(unittest.TestCase):
    def test_missing_event_date_surfaces_distinct_blocker(self) -> None:
        state = _state(
            events={60: {"event_date": None, "primary_ticker": "XOM"}},
            cache={"XOM": [], "XLE": []},
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["can_run_sensitivity"])
        self.assertEqual(row["blocker_reason"], "missing_event_date")
        self.assertEqual(row["missing_primary_ranges"], [])
        self.assertEqual(row["missing_benchmark_ranges"], [])

    def test_missing_primary_ticker_surfaces_distinct_blocker(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": None}},
            cache={"XLE": _full_cache_for(ev_date)},
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["can_run_sensitivity"])
        self.assertEqual(row["blocker_reason"], "missing_primary_ticker")
        self.assertFalse(row["primary_cache_available"])
        # Benchmark cache check still runs even without primary ticker.
        self.assertTrue(row["benchmark_cache_available"])

    def test_unknown_event_id_surfaces_missing_event_date_blocker(self) -> None:
        # No events were loaded — the preflight should still surface a
        # row for the requested id with an explicit blocker, not crash.
        state = _state(events={}, cache={})
        result = _run(state=state, event_ids=(999,), benchmark="XLE")
        row = result["rows"][0]
        self.assertEqual(row["event_id"], 999)
        self.assertFalse(row["can_run_sensitivity"])
        self.assertEqual(row["blocker_reason"], "missing_event_date")


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------


class TestRecommendedAction(unittest.TestCase):
    def test_all_ready_recommendation_mentions_benchmark(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=80, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        rec = result["recommended_next_action"]
        self.assertIn("XLE", rec)
        self.assertIn("benchmark sensitivity", rec.lower())

    def test_blocked_recommendation_mentions_backfill_and_ranges(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date),
                "XLE": _full_cache_for(ev_date, pre_count=58, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        rec = result["recommended_next_action"].lower()
        self.assertIn("backfill", rec)
        self.assertIn("price_cache", rec)

    def test_no_events_recommendation_is_well_formed(self) -> None:
        result = _run(state=_state(events={}, cache={}), event_ids=())
        rec = result["recommended_next_action"]
        self.assertGreater(len(rec.strip()), 0)

    def test_recommended_action_avoids_banned_words(self) -> None:
        ev_date = date(2026, 4, 8)
        for state_kwargs in (
            # ready state
            dict(
                events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
                cache={
                    "XOM": _full_cache_for(ev_date),
                    "XLE": _full_cache_for(ev_date),
                },
            ),
            # blocked state
            dict(
                events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
                cache={"XOM": _full_cache_for(ev_date), "XLE": []},
            ),
            # empty
            dict(events={}, cache={}),
        ):
            with self.subTest(state=state_kwargs):
                if state_kwargs.get("events"):
                    result = _run(state=_state(**state_kwargs), event_ids=(60,))
                else:
                    result = _run(state=_state(**state_kwargs), event_ids=())
                rec = result["recommended_next_action"].lower()
                for w in _BANNED_WORDS:
                    self.assertNotIn(w, rec, f"banned word {w!r} in: {rec!r}")

    def test_blocker_reason_avoids_banned_words(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date),
                "XLE": _full_cache_for(ev_date, pre_count=58, forward_count=30),
            },
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        reason = result["rows"][0]["blocker_reason"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, reason, f"banned word {w!r} in: {reason!r}")


# ---------------------------------------------------------------------------
# Seam
# ---------------------------------------------------------------------------


class TestSeam(unittest.TestCase):
    def test_load_archive_state_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_load_archive_state")))

    def test_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake(*, db_path, event_ids, tickers):
            captured.setdefault("calls", []).append({
                "db_path":   db_path,
                "event_ids": tuple(event_ids),
                "tickers":   tuple(tickers),
            })
            return {"events": {}, "cache": {}}

        with patch.object(cli, "_load_archive_state", side_effect=fake):
            cli.summarize_benchmark_sensitivity_preflight(
                db_path="/sentinel/path.db",
                event_ids=(60, 73),
            )
        # The seam may be called twice (one to discover primary tickers,
        # one to fetch their caches), but every call must carry the
        # operator-supplied db_path.
        self.assertGreaterEqual(len(captured.get("calls", [])), 1)
        for call in captured["calls"]:
            self.assertEqual(call["db_path"], "/sentinel/path.db")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestPureHelpers(unittest.TestCase):
    def test_business_day_offset_forward(self) -> None:
        # 2026-04-08 is a Wednesday; +5bd = next Wednesday (2026-04-15).
        self.assertEqual(
            cli._business_day_offset(date(2026, 4, 8), 5),
            date(2026, 4, 15),
        )

    def test_business_day_offset_skips_weekend(self) -> None:
        # Friday + 1bd = Monday.
        friday = date(2026, 4, 10)
        self.assertEqual(friday.weekday(), 4)
        self.assertEqual(
            cli._business_day_offset(friday, 1), date(2026, 4, 13))

    def test_business_day_offset_negative(self) -> None:
        # Monday - 1bd = previous Friday.
        monday = date(2026, 4, 13)
        self.assertEqual(monday.weekday(), 0)
        self.assertEqual(
            cli._business_day_offset(monday, -1), date(2026, 4, 10))

    def test_business_day_offset_zero(self) -> None:
        d = date(2026, 4, 8)
        self.assertEqual(cli._business_day_offset(d, 0), d)


# ---------------------------------------------------------------------------
# Market-holiday handling
# ---------------------------------------------------------------------------


class TestMarketHolidayHelpers(unittest.TestCase):
    """Pin the holiday-aware date helpers used by the missing-range logic.

    The preflight runs without importing ``market_check`` (see
    ``TestImportIsolation``) so it carries its own small NYSE calendar.
    These tests confirm the helpers handle the known closure dates used
    by the integration tests below.
    """

    def test_market_holiday_set_includes_2026_new_year(self) -> None:
        holidays = getattr(cli, "_MARKET_HOLIDAYS", frozenset())
        self.assertIn(date(2026, 1, 1), holidays)

    def test_market_holiday_set_includes_2025_christmas(self) -> None:
        # 2025-12-25 lands on a Thursday — needed for the
        # forward-horizon-crosses-Christmas+NewYear scenario below.
        holidays = getattr(cli, "_MARKET_HOLIDAYS", frozenset())
        self.assertIn(date(2025, 12, 25), holidays)

    def test_is_trading_day_returns_false_for_market_holiday(self) -> None:
        # 2026-01-01 is a Thursday (a weekday) but NYSE is closed.
        self.assertFalse(cli._is_trading_day(date(2026, 1, 1)))

    def test_is_trading_day_returns_false_for_weekend(self) -> None:
        # 2026-01-03 is a Saturday.
        self.assertFalse(cli._is_trading_day(date(2026, 1, 3)))

    def test_is_trading_day_returns_true_for_normal_weekday(self) -> None:
        # 2026-01-02 is a Friday and not a holiday.
        self.assertTrue(cli._is_trading_day(date(2026, 1, 2)))

    def test_trading_day_offset_forward_skips_holiday(self) -> None:
        # 2025-12-31 (Wed) + 1 trading day = 2026-01-02 (Fri),
        # skipping Jan 1 (NYE-observed New Year's Day).
        self.assertEqual(
            cli._trading_day_offset(date(2025, 12, 31), 1),
            date(2026, 1, 2),
        )

    def test_trading_day_offset_negative_skips_holiday(self) -> None:
        # 2026-01-02 (Fri) - 1 trading day = 2025-12-31 (Wed),
        # skipping Jan 1.
        self.assertEqual(
            cli._trading_day_offset(date(2026, 1, 2), -1),
            date(2025, 12, 31),
        )

    def test_trading_day_offset_zero_returns_input(self) -> None:
        d = date(2026, 4, 8)
        self.assertEqual(cli._trading_day_offset(d, 0), d)

    def test_trading_day_offset_skips_weekend_like_business_day(self) -> None:
        # Friday + 1 trading day = Monday (no intervening holiday).
        friday = date(2026, 4, 10)
        self.assertEqual(
            cli._trading_day_offset(friday, 1), date(2026, 4, 13))


# The full 2026 NYSE/Nasdaq observed-closure roster the task pins.
# Every entry must be treated as non-trading by the preflight; a real
# ``price_cache`` will never contain a row for any of these dates, so
# the missing-range logic must never demand one.
_2026_NYSE_HOLIDAYS: tuple[tuple[date, str], ...] = (
    (date(2026, 1, 1),   "New Year's Day"),
    (date(2026, 1, 19),  "MLK Day"),
    (date(2026, 2, 16),  "Presidents' Day"),
    (date(2026, 4, 3),   "Good Friday"),
    (date(2026, 5, 25),  "Memorial Day"),
    (date(2026, 6, 19),  "Juneteenth"),
    (date(2026, 7, 3),   "Independence Day (obs.)"),
    (date(2026, 9, 7),   "Labor Day"),
    (date(2026, 11, 26), "Thanksgiving"),
    (date(2026, 12, 25), "Christmas"),
)


class Test2026HolidayRoster(unittest.TestCase):
    """Pin the full 2026 NYSE closure calendar end-to-end.

    Each listed date must (a) be in ``_MARKET_HOLIDAYS``,
    (b) return ``False`` from ``_is_trading_day``, and (c) be omitted
    from the estimation-window required-dates set so a missing
    cache row for that date alone does not block an event.

    Non-holiday weekdays adjacent to each holiday must still register
    as trading days so the fix does not over-broaden.
    """

    def test_each_2026_holiday_is_in_market_holidays_set(self) -> None:
        holidays = getattr(cli, "_MARKET_HOLIDAYS", frozenset())
        for d, name in _2026_NYSE_HOLIDAYS:
            with self.subTest(date=d.isoformat(), name=name):
                self.assertIn(d, holidays)

    def test_each_2026_holiday_is_not_a_trading_day(self) -> None:
        for d, name in _2026_NYSE_HOLIDAYS:
            with self.subTest(date=d.isoformat(), name=name):
                self.assertFalse(cli._is_trading_day(d))

    def test_each_2026_holiday_lands_on_a_weekday(self) -> None:
        # Sanity: if the roster lists a Saturday/Sunday, the
        # weekday-only old code never would have demanded it anyway,
        # so the fix would not be observable for that entry.  All
        # listed 2026 dates must be Mon-Fri to exercise the bug.
        for d, name in _2026_NYSE_HOLIDAYS:
            with self.subTest(date=d.isoformat(), name=name):
                self.assertLess(d.weekday(), 5)

    def test_each_2026_holiday_is_omitted_from_required_pre_dates(self) -> None:
        # Anchor 30 calendar days after each holiday so the
        # ``estimation_window`` lookback brackets the holiday.
        for d, name in _2026_NYSE_HOLIDAYS:
            with self.subTest(date=d.isoformat(), name=name):
                event_d = d + timedelta(days=30)
                required = cli._trading_days_before(event_d, 60)
                self.assertNotIn(d, required)
                # The day before and the day after each holiday are
                # usually trading days; sanity-check one neighbour
                # falls inside the required set so the test would
                # fail loudly if the helper became overly aggressive.
                neighbour = d - timedelta(days=1)
                while neighbour.weekday() >= 5 or neighbour in cli._MARKET_HOLIDAYS:
                    neighbour = neighbour - timedelta(days=1)
                self.assertIn(neighbour, required)

    def test_each_2026_holiday_does_not_block_event_when_only_gap(self) -> None:
        # Build a cache whose only "missing" date is the holiday in
        # question.  The preflight must clear the event.
        for d, name in _2026_NYSE_HOLIDAYS:
            with self.subTest(date=d.isoformat(), name=name):
                event_d = d + timedelta(days=30)
                # Cache spans 120 calendar days back through 60
                # calendar days forward of the event, holiday-aware.
                pre = _trading_days_inclusive(
                    event_d - timedelta(days=120),
                    event_d - timedelta(days=1),
                )
                fwd = _trading_days_inclusive(
                    event_d, event_d + timedelta(days=60),
                )
                cache = sorted(set(pre + fwd))
                # Sanity: holiday itself was never inserted.
                self.assertNotIn(d.isoformat(), cache)

                state = _state(
                    events={60: {
                        "event_date":     event_d.isoformat(),
                        "primary_ticker": "XOM",
                    }},
                    cache={"XOM": cache, "XLE": cache},
                )
                result = _run(state=state, event_ids=(60,), benchmark="XLE")
                row = result["rows"][0]
                self.assertTrue(
                    row["can_run_sensitivity"],
                    msg=(
                        f"holiday {d.isoformat()} ({name}) wrongly "
                        f"blocked event with otherwise-complete cache; "
                        f"missing={row['missing_benchmark_ranges']}"
                    ),
                )
                self.assertEqual(row["missing_benchmark_ranges"], [])
                self.assertEqual(row["missing_primary_ranges"],   [])

    def test_non_holiday_weekday_adjacent_to_each_holiday_still_required(self) -> None:
        # For each 2026 holiday, drop the NEXT trading day after the
        # holiday from the cache and verify the preflight blocks.
        # Confirms the fix did not silently broaden to "the day after
        # any holiday is also non-trading".
        for d, name in _2026_NYSE_HOLIDAYS:
            with self.subTest(date=d.isoformat(), name=name):
                event_d = d + timedelta(days=30)
                next_trading = cli._trading_day_offset(d, 1)
                # If the next trading day is after event_d, this
                # subtest is moot — but for every listed 2026
                # holiday the +30-day event leaves room.
                self.assertLess(next_trading, event_d)

                pre_full = _trading_days_inclusive(
                    event_d - timedelta(days=120),
                    event_d - timedelta(days=1),
                )
                pre_minus_one = [
                    iso for iso in pre_full
                    if iso != next_trading.isoformat()
                ]
                fwd = _trading_days_inclusive(
                    event_d, event_d + timedelta(days=60),
                )
                cache = sorted(set(pre_minus_one + fwd))

                state = _state(
                    events={60: {
                        "event_date":     event_d.isoformat(),
                        "primary_ticker": "XOM",
                    }},
                    cache={"XOM": cache, "XLE": cache},
                )
                result = _run(state=state, event_ids=(60,), benchmark="XLE")
                row = result["rows"][0]
                # A real trading day was dropped — preflight must block.
                self.assertFalse(
                    row["can_run_sensitivity"],
                    msg=(
                        f"dropping non-holiday trading day "
                        f"{next_trading.isoformat()} after "
                        f"{d.isoformat()} ({name}) failed to block; "
                        f"the holiday filter is too aggressive"
                    ),
                )
                reasons = {
                    r["reason"] for r in row["missing_benchmark_ranges"]
                }
                self.assertIn("estimation_window_short", reasons)


class TestEstimationWindowHolidayHandling(unittest.TestCase):
    """The estimation-window check must not flag market-holiday rows
    that can never exist in a real ``price_cache``.

    Mirrors the live archive state observed in the manual-review
    backlog: after ``xle_online_backfill_preview`` fetched ``Dec 30``,
    ``Dec 31``, and ``Jan 2`` and reported ``2026-01-01`` in
    ``still_missing_dates``, the temp-DB preflight should clear the
    event because the only remaining gap is a known NYSE-closed day.
    """

    def test_jan_1_holiday_does_not_block_when_other_rows_present(self) -> None:
        # Event 73 with event_date 2026-02-02 (Mon).  The most-recent
        # 60 trading days before that date stretch from mid-November
        # 2025 to Jan 30 2026 and cross 2026-01-01 (a NYSE holiday).
        ev_date = date(2026, 2, 2)
        pre_dates = _trading_days_inclusive(
            date(2025, 9, 1), date(2026, 1, 30))
        fwd_dates = _trading_days_inclusive(
            ev_date, date(2026, 4, 30))
        cache = sorted(set(pre_dates + fwd_dates))
        # Sanity: 2026-01-01 must NOT be in the synthetic cache —
        # real price_cache never has a row for a market holiday.
        self.assertNotIn("2026-01-01", cache)

        state = _state(
            events={73: {
                "event_date":     ev_date.isoformat(),
                "primary_ticker": "XOM",
            }},
            cache={"XOM": cache, "XLE": cache},
        )
        result = _run(state=state, event_ids=(73,), benchmark="XLE")
        row = result["rows"][0]
        self.assertTrue(row["primary_cache_available"])
        self.assertTrue(row["benchmark_cache_available"])
        self.assertTrue(row["can_run_sensitivity"])
        self.assertEqual(row["missing_primary_ranges"],    [])
        self.assertEqual(row["missing_benchmark_ranges"],  [])
        self.assertEqual(row["blocker_reason"], "ready")

    def test_event_73_clears_once_dec_30_dec_31_and_jan_2_exist(self) -> None:
        # Reproduces the temp-preview shape: an event whose
        # estimation-window deficit was originally 4 business days
        # ([Dec 30, Dec 31, Jan 1, Jan 2]).  The operator-approved
        # backfill brought back Dec 30, Dec 31, Jan 2; Jan 1 stays
        # absent because the market is closed.  The preflight should
        # NOT keep the event blocked on the holiday.
        ev_date = date(2026, 2, 2)
        # 60 trading days before 2026-02-02 reach ~mid-November 2025.
        pre_dates = _trading_days_inclusive(
            date(2025, 11, 1), date(2026, 1, 30))
        # Explicitly assert the three real-trading dates exist and
        # the holiday does not.
        self.assertIn("2025-12-30", pre_dates)
        self.assertIn("2025-12-31", pre_dates)
        self.assertIn("2026-01-02", pre_dates)
        self.assertNotIn("2026-01-01", pre_dates)
        fwd_dates = _trading_days_inclusive(
            ev_date, date(2026, 4, 30))
        cache = sorted(set(pre_dates + fwd_dates))
        state = _state(
            events={73: {
                "event_date":     ev_date.isoformat(),
                "primary_ticker": "XOM",
            }},
            cache={"XOM": cache, "XLE": cache},
        )
        result = _run(state=state, event_ids=(73,), benchmark="XLE")
        self.assertEqual(result["ready_count"],   1)
        self.assertEqual(result["blocked_count"], 0)

    def test_non_holiday_business_day_gap_still_blocks(self) -> None:
        # A real (non-holiday) trading-day gap in the estimation
        # window must still surface as a blocker.  The fix may NOT
        # silently absorb real gaps.
        ev_date = date(2026, 2, 2)
        # Build a cache that drops one ordinary trading day
        # (2026-01-05, a Monday) from the most-recent 60 window.
        pre_dates = [
            d for d in _trading_days_inclusive(
                date(2025, 9, 1), date(2026, 1, 30))
            if d != "2026-01-05"
        ]
        fwd_dates = _trading_days_inclusive(
            ev_date, date(2026, 4, 30))
        cache = sorted(set(pre_dates + fwd_dates))
        state = _state(
            events={73: {
                "event_date":     ev_date.isoformat(),
                "primary_ticker": "XOM",
            }},
            cache={"XOM": cache, "XLE": cache},
        )
        result = _run(state=state, event_ids=(73,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["benchmark_cache_available"])
        self.assertFalse(row["can_run_sensitivity"])
        reasons = {r["reason"] for r in row["missing_benchmark_ranges"]}
        self.assertIn("estimation_window_short", reasons)


class TestForwardHorizonHolidayHandling(unittest.TestCase):
    """Forward horizons are interpreted as trading days, not weekdays.

    Required behavior:

      * A cache that reaches the N-th *trading day* after the event
        is sufficient even when the N-th weekday would land on a
        market holiday.
      * A cache that stops short of the N-th *trading day* still
        emits a forward-horizon-gap.  We do NOT weaken coverage.
    """

    def test_forward_horizon_clears_when_cache_reaches_nth_trading_day(self) -> None:
        # Event 2025-12-05 (Fri).  Default horizons (1, 5, 20).
        # 20 trading days after Dec 5 lands at 2026-01-06 (Tue) —
        # the path skips Dec 25 (Christmas) and Jan 1 (New Year).
        # 20 *weekdays* after Dec 5 would naively be 2026-01-02 (Fri).
        ev_date = date(2025, 12, 5)
        pre_dates = _trading_days_inclusive(
            date(2025, 6, 1), date(2025, 12, 4))
        # Cache reaches Jan 6 — the actual 20th trading day.
        fwd_dates = _trading_days_inclusive(
            ev_date, date(2026, 1, 6))
        cache = sorted(set(pre_dates + fwd_dates))
        state = _state(
            events={60: {
                "event_date":     ev_date.isoformat(),
                "primary_ticker": "XOM",
            }},
            cache={"XOM": cache, "XLE": cache},
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertTrue(row["benchmark_cache_available"])
        self.assertEqual(row["missing_benchmark_ranges"], [])

    def test_forward_horizon_blocks_when_cache_short_of_nth_trading_day(self) -> None:
        # Same event; cache stops at Jan 2 (only 18 trading days
        # after Dec 5 once Dec 25 and Jan 1 are excluded).  The
        # forward horizon of 20 trading days is NOT satisfied.
        ev_date = date(2025, 12, 5)
        pre_dates = _trading_days_inclusive(
            date(2025, 6, 1), date(2025, 12, 4))
        fwd_dates = _trading_days_inclusive(
            ev_date, date(2026, 1, 2))
        cache = sorted(set(pre_dates + fwd_dates))
        state = _state(
            events={60: {
                "event_date":     ev_date.isoformat(),
                "primary_ticker": "XOM",
            }},
            cache={"XOM": cache, "XLE": cache},
        )
        result = _run(state=state, event_ids=(60,), benchmark="XLE")
        row = result["rows"][0]
        self.assertFalse(row["benchmark_cache_available"])
        reasons = {r["reason"] for r in row["missing_benchmark_ranges"]}
        self.assertIn("forward_horizon_gap", reasons)


# ---------------------------------------------------------------------------
# JSON CLI
# ---------------------------------------------------------------------------


class TestJSONCLI(unittest.TestCase):
    def test_json_cli_round_trips(self) -> None:
        ev_date = date(2026, 4, 8)
        state = _state(
            events={60: {"event_date": ev_date.isoformat(), "primary_ticker": "XOM"}},
            cache={
                "XOM": _full_cache_for(ev_date, pre_count=80, forward_count=30),
                "XLE": _full_cache_for(ev_date, pre_count=80, forward_count=30),
            },
        )
        rc, output = _run_cli(["--json", "--event-ids", "60"], state=state)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _TOP_LEVEL_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["checked_events"], 1)
        self.assertEqual(parsed["ready_count"], 1)

    def test_text_cli_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [], state=_state(events={}, cache={}),
        )
        self.assertEqual(rc, 0)
        self.assertGreater(len(output.strip()), 0)


# ---------------------------------------------------------------------------
# Read-only / import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance",
        "market_check",
        "market_data",
        "price_cache",
        "api",
        "fastapi",
    )

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        with patch.object(
            cli, "_load_archive_state",
            return_value={"events": {}, "cache": {}},
        ):
            cli.summarize_benchmark_sensitivity_preflight(event_ids=())
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


if __name__ == "__main__":
    unittest.main()
