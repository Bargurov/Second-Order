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


def _full_cache_for(
    event_date: date, *,
    pre_count: int = 60,
    forward_count: int = 30,
) -> list[str]:
    """A cache that satisfies estimation-window AND forward-horizon
    checks for the given event_date.

    ``pre_count`` distinct business days strictly before ``event_date``
    + ``forward_count`` business days from ``event_date`` onward.
    """
    # Walk back ``pre_count`` business days, then build forward.
    cur = event_date
    one = timedelta(days=1)
    pre: list[str] = []
    while len(pre) < pre_count:
        cur = cur - one
        if cur.weekday() < 5:
            pre.append(cur.isoformat())
    pre.reverse()
    forward = _bd_dates(event_date, forward_count)
    # ``forward[0]`` is the event_date itself if it is a weekday; that's
    # acceptable — the readiness logic only uses dates strictly before
    # event for estimation and dates >= +1bd for forward.
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
