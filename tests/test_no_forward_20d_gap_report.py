"""Tests for ``scripts/no_forward_20d_gap_report.py`` — focused report
that summarises remaining ``no_forward_20d`` gaps.

The CLI is read-only: it reuses the existing diagnostics breakdown
(:func:`routes.diagnostics._compute_no_forward_20d_breakdown`) and
reshapes the output into operator-facing fields.  These tests pin:

  * JSON / text output shape — top-level keys and content.
  * Category-count mapping from the breakdown's
    ``event_too_recent_for_20d`` / ``auto_adjust_mismatch_for_20d`` /
    ``cache_max_before_20d_horizon`` / ``likely_delisted_or_sparse``
    keys onto the user-facing ``too_recent`` / ``auto_adjust_mismatch``
    / ``cache_window_gap`` / ``likely_delisted_or_sparse`` keys.
  * Refreshable vs non-refreshable example partitioning.  Only
    ``cache_max_before_20d_horizon`` examples are refreshable; the
    other three sub-reasons are inherently non-refreshable (the
    breakdown's own docstring says so).
  * ``recommended_next_action`` decision tree.
  * ``--limit`` truncation behaviour, including the source cap (the
    breakdown caps internal examples at 10, so ``--limit 100`` cannot
    exceed that).
  * ``available=False`` short-circuit returns all-zero counts and the
    no-action recommendation.
  * No DB writes — the report leaves ``events`` and ``price_cache``
    byte-identical across repeated runs.
  * No provider, yfinance, market_check, market_data, price_cache,
    LLM, or FastAPI seam is invoked by the report.

The breakdown function itself is exercised by
``tests/test_diagnostics.py``; this test scopes the CLI's reshape +
recommendation surface and the read-only contract.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402,F401  — pre-loads routes.diagnostics so the
                                #  CLI's lazy ``_compute_breakdown``
                                #  import doesn't trip the
                                #  api ↔ routes.diagnostics cycle when
                                #  the un-patched seam is exercised
                                #  (TestNoMutation).
import db  # noqa: E402
from scripts import no_forward_20d_gap_report as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic breakdowns — drive the CLI without touching the real DB graph.
# ---------------------------------------------------------------------------


def _example(event_id: int, ticker: str, diag_reason: str) -> dict:
    return {
        "event_id":          event_id,
        "headline":          f"NF20 {diag_reason} #{event_id}",
        "ticker":            ticker,
        "missing_reason":    "no_forward_20d_close",
        "diagnostic_reason": diag_reason,
    }


_FAKE_BREAKDOWN_ALL_FOUR = {
    "available": True,
    "total_no_forward_20d": 4,
    "counts": {
        "event_too_recent_for_20d":     1,
        "auto_adjust_mismatch_for_20d": 1,
        "cache_max_before_20d_horizon": 1,
        "likely_delisted_or_sparse":    1,
    },
    "examples": [
        _example(1, "AAPL",    "event_too_recent_for_20d"),
        _example(2, "MSFT",    "auto_adjust_mismatch_for_20d"),
        _example(3, "GOOG",    "cache_max_before_20d_horizon"),
        _example(4, "OBSCURE", "likely_delisted_or_sparse"),
    ],
}


_FAKE_BREAKDOWN_EMPTY = {
    "available": True,
    "total_no_forward_20d": 0,
    "counts": {
        "event_too_recent_for_20d":     0,
        "auto_adjust_mismatch_for_20d": 0,
        "cache_max_before_20d_horizon": 0,
        "likely_delisted_or_sparse":    0,
    },
    "examples": [],
}


_FAKE_BREAKDOWN_UNAVAILABLE = {
    "available": False,
    "total_no_forward_20d": 0,
    "counts": {
        "event_too_recent_for_20d":     0,
        "auto_adjust_mismatch_for_20d": 0,
        "cache_max_before_20d_horizon": 0,
        "likely_delisted_or_sparse":    0,
    },
    "examples": [],
}


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# JSON shape + category mapping
# ---------------------------------------------------------------------------


_REQUIRED_TOP_KEYS = (
    "total_no_forward_20d",
    "too_recent",
    "auto_adjust_mismatch",
    "cache_window_gap",
    "likely_delisted_or_sparse",
    "refreshable_gap_examples",
    "non_refreshable_examples",
    "auto_adjust_mismatch_details",
    "recommended_next_action",
)


_DETAIL_KEYS = (
    "event_id",
    "event_date",
    "symbol",
    "available_auto_adjust_flags",
    "cache_max_per_flag",
    "recommended_action",
)


class TestPayloadShape(unittest.TestCase):
    def test_json_emits_every_required_top_level_key(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_ALL_FOUR):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _REQUIRED_TOP_KEYS:
            self.assertIn(key, body, f"missing JSON key: {key}")

    def test_json_empty_breakdown_serialises_to_zeroes(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_EMPTY):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_no_forward_20d"],      0)
        self.assertEqual(body["too_recent"],                0)
        self.assertEqual(body["auto_adjust_mismatch"],      0)
        self.assertEqual(body["cache_window_gap"],          0)
        self.assertEqual(body["likely_delisted_or_sparse"], 0)
        self.assertEqual(body["refreshable_gap_examples"],  [])
        self.assertEqual(body["non_refreshable_examples"],  [])


class TestCategoryMapping(unittest.TestCase):
    def test_each_category_count_maps_correctly(self) -> None:
        breakdown = {
            "available": True,
            "total_no_forward_20d": 14,
            "counts": {
                "event_too_recent_for_20d":     2,
                "auto_adjust_mismatch_for_20d": 3,
                "cache_max_before_20d_horizon": 5,
                "likely_delisted_or_sparse":    4,
            },
            "examples": [],
        }
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["total_no_forward_20d"],      14)
        self.assertEqual(body["too_recent"],                2)
        self.assertEqual(body["auto_adjust_mismatch"],      3)
        self.assertEqual(body["cache_window_gap"],          5)
        self.assertEqual(body["likely_delisted_or_sparse"], 4)


# ---------------------------------------------------------------------------
# Refreshable vs non-refreshable partitioning
# ---------------------------------------------------------------------------


class TestRefreshablePartitioning(unittest.TestCase):
    def test_only_cache_window_gap_examples_are_refreshable(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_ALL_FOUR):
            _, output = _run_cli(["--json"])
        body = json.loads(output)

        refreshable = body["refreshable_gap_examples"]
        self.assertEqual(len(refreshable), 1)
        self.assertEqual(
            refreshable[0]["diagnostic_reason"],
            "cache_max_before_20d_horizon",
        )
        self.assertEqual(refreshable[0]["ticker"], "GOOG")

    def test_other_three_sub_reasons_are_non_refreshable(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_ALL_FOUR):
            _, output = _run_cli(["--json"])
        body = json.loads(output)

        non_refreshable = body["non_refreshable_examples"]
        self.assertEqual(len(non_refreshable), 3)
        diag_reasons = {e["diagnostic_reason"] for e in non_refreshable}
        self.assertEqual(diag_reasons, {
            "event_too_recent_for_20d",
            "auto_adjust_mismatch_for_20d",
            "likely_delisted_or_sparse",
        })

    def test_partitions_are_disjoint(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_ALL_FOUR):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        ref_ids = {e["event_id"] for e in body["refreshable_gap_examples"]}
        non_ids = {e["event_id"] for e in body["non_refreshable_examples"]}
        self.assertEqual(
            ref_ids & non_ids, set(),
            "refreshable / non-refreshable partitions must be disjoint",
        )


# ---------------------------------------------------------------------------
# recommended_next_action decision tree
# ---------------------------------------------------------------------------


class TestRecommendedAction(unittest.TestCase):
    def _action_for(self, counts: dict) -> str:
        breakdown = {
            "available": True,
            "total_no_forward_20d": sum(counts.values()),
            "counts": counts,
            "examples": [],
        }
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown):
            _, output = _run_cli(["--json"])
        return json.loads(output)["recommended_next_action"]

    def test_no_gaps_recommends_no_action(self) -> None:
        action = self._action_for({
            "event_too_recent_for_20d":     0,
            "auto_adjust_mismatch_for_20d": 0,
            "cache_max_before_20d_horizon": 0,
            "likely_delisted_or_sparse":    0,
        })
        self.assertEqual(action, "no_action_needed_no_gaps")

    def test_auto_adjust_mismatch_only(self) -> None:
        action = self._action_for({
            "event_too_recent_for_20d":     0,
            "auto_adjust_mismatch_for_20d": 5,
            "cache_max_before_20d_horizon": 0,
            "likely_delisted_or_sparse":    0,
        })
        self.assertEqual(action, "fix_auto_adjust_flag_mismatch")

    def test_cache_window_gap_only(self) -> None:
        action = self._action_for({
            "event_too_recent_for_20d":     0,
            "auto_adjust_mismatch_for_20d": 0,
            "cache_max_before_20d_horizon": 7,
            "likely_delisted_or_sparse":    0,
        })
        self.assertEqual(action, "run_targeted_refresh_for_cache_window_gap")

    def test_too_recent_only(self) -> None:
        action = self._action_for({
            "event_too_recent_for_20d":     3,
            "auto_adjust_mismatch_for_20d": 0,
            "cache_max_before_20d_horizon": 0,
            "likely_delisted_or_sparse":    0,
        })
        self.assertEqual(action, "wait_or_accept_no_refreshable_gaps")

    def test_likely_delisted_only(self) -> None:
        action = self._action_for({
            "event_too_recent_for_20d":     0,
            "auto_adjust_mismatch_for_20d": 0,
            "cache_max_before_20d_horizon": 0,
            "likely_delisted_or_sparse":    4,
        })
        self.assertEqual(action, "wait_or_accept_no_refreshable_gaps")

    def test_mixed_auto_adjust_takes_priority_over_cache_gap(self) -> None:
        # Cache-already-has-data is cheaper than re-fetching, so the
        # priority order is: auto_adjust_mismatch first.
        action = self._action_for({
            "event_too_recent_for_20d":     0,
            "auto_adjust_mismatch_for_20d": 1,
            "cache_max_before_20d_horizon": 9,
            "likely_delisted_or_sparse":    0,
        })
        self.assertEqual(action, "fix_auto_adjust_flag_mismatch")

    def test_mixed_cache_gap_over_too_recent_and_delisted(self) -> None:
        action = self._action_for({
            "event_too_recent_for_20d":     2,
            "auto_adjust_mismatch_for_20d": 0,
            "cache_max_before_20d_horizon": 1,
            "likely_delisted_or_sparse":    3,
        })
        self.assertEqual(action, "run_targeted_refresh_for_cache_window_gap")


# ---------------------------------------------------------------------------
# --limit flag
# ---------------------------------------------------------------------------


def _seven_examples() -> list[dict]:
    return [
        _example(10, "AAPL", "cache_max_before_20d_horizon"),
        _example(11, "MSFT", "cache_max_before_20d_horizon"),
        _example(12, "NVDA", "cache_max_before_20d_horizon"),
        _example(13, "AMZN", "cache_max_before_20d_horizon"),
        _example(20, "TSLA", "event_too_recent_for_20d"),
        _example(21, "META", "event_too_recent_for_20d"),
        _example(22, "ZZZZ", "likely_delisted_or_sparse"),
    ]


class TestLimitFlag(unittest.TestCase):
    def test_default_limit_returns_up_to_ten_per_partition(self) -> None:
        breakdown = {
            "available": True,
            "total_no_forward_20d": 7,
            "counts": {
                "event_too_recent_for_20d":     2,
                "auto_adjust_mismatch_for_20d": 0,
                "cache_max_before_20d_horizon": 4,
                "likely_delisted_or_sparse":    1,
            },
            "examples": _seven_examples(),
        }
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(len(body["refreshable_gap_examples"]),  4)
        self.assertEqual(len(body["non_refreshable_examples"]),  3)

    def test_limit_truncates_each_partition(self) -> None:
        breakdown = {
            "available": True,
            "total_no_forward_20d": 7,
            "counts": {
                "event_too_recent_for_20d":     2,
                "auto_adjust_mismatch_for_20d": 0,
                "cache_max_before_20d_horizon": 4,
                "likely_delisted_or_sparse":    1,
            },
            "examples": _seven_examples(),
        }
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown):
            _, output = _run_cli(["--json", "--limit", "2"])
        body = json.loads(output)
        self.assertEqual(len(body["refreshable_gap_examples"]),  2)
        self.assertEqual(len(body["non_refreshable_examples"]),  2)

    def test_limit_above_source_supply_returns_source_supply(self) -> None:
        # The breakdown caps internal examples at 10 — `--limit 100`
        # cannot conjure more examples than the breakdown delivered.
        # Pin the cap so a future change to the source's example budget
        # surfaces here loudly.
        breakdown = {
            "available": True,
            "total_no_forward_20d": 7,
            "counts": {
                "event_too_recent_for_20d":     2,
                "auto_adjust_mismatch_for_20d": 0,
                "cache_max_before_20d_horizon": 4,
                "likely_delisted_or_sparse":    1,
            },
            "examples": _seven_examples(),
        }
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown):
            _, output = _run_cli(["--json", "--limit", "100"])
        body = json.loads(output)
        self.assertEqual(len(body["refreshable_gap_examples"]),  4)
        self.assertEqual(len(body["non_refreshable_examples"]),  3)


# ---------------------------------------------------------------------------
# Unavailable-breakdown short-circuit
# ---------------------------------------------------------------------------


class TestUnavailableBreakdown(unittest.TestCase):
    def test_unavailable_breakdown_returns_zeroes_and_no_action(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_UNAVAILABLE):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_no_forward_20d"],      0)
        self.assertEqual(body["too_recent"],                0)
        self.assertEqual(body["auto_adjust_mismatch"],      0)
        self.assertEqual(body["cache_window_gap"],          0)
        self.assertEqual(body["likely_delisted_or_sparse"], 0)
        self.assertEqual(body["refreshable_gap_examples"],  [])
        self.assertEqual(body["non_refreshable_examples"],  [])
        self.assertEqual(body["recommended_next_action"],
                         "no_action_needed_no_gaps")


# ---------------------------------------------------------------------------
# Default text rendering
# ---------------------------------------------------------------------------


class TestTextRendering(unittest.TestCase):
    def test_text_lists_every_count_label(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_ALL_FOUR):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        for needle in (
            "Total no_forward_20d",
            "Too recent",
            "Auto-adjust mismatch",
            "Cache window gap",
            "Likely delisted or sparse",
            "Refreshable",
            "Non-refreshable",
            "Recommended next action",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_text_surfaces_the_recommendation(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FAKE_BREAKDOWN_ALL_FOUR):
            _, output = _run_cli([])
        # All four buckets nonzero — auto_adjust_mismatch wins by
        # priority.
        self.assertIn("fix_auto_adjust_flag_mismatch", output)


# ---------------------------------------------------------------------------
# Read-only contract — temp DB, no mutation
# ---------------------------------------------------------------------------


def _snapshot_tables(db_path: str) -> tuple[list[tuple], list[tuple]]:
    conn = sqlite3.connect(db_path)
    try:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        cache = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


class TestNoMutation(unittest.TestCase):
    """End-to-end read-only contract — let the real breakdown run
    against a temp SQLite fixture and confirm both tables are
    byte-identical before and after repeated CLI runs.
    """

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_nf20_gap_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

        # Plant a price_cache row and an event so the breakdown has
        # something to traverse — proves the repeated calls don't
        # disturb either table.
        record = {
            "headline":   "NF20 gap report no-mutation probe",
            "stage":      "realized",
            "persistence": "medium",
            "event_date": "2026-01-10",
            "market_tickers": [{"symbol": "AAPL"}],
        }
        db.save_event(record)
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-01-15", 100.0, 5_000_000.0, 0,
                 "2026-05-06T12:00:00+00:00"),
            )
            conn.commit()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            rc, _ = _run_cli(["--json"])
            self.assertEqual(rc, 0)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical before and "
            "after repeated gap-report runs",
        )


# ---------------------------------------------------------------------------
# No-provider-call invariant — same shape as the planner's contract test.
# ---------------------------------------------------------------------------


class TestNoProviderCalls(unittest.TestCase):
    """The CLI must never call market_check, market_data, yfinance,
    fetch_daily_cached, or any LLM seam."""

    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("price_cache",  "_purge_corrupt_rows"),
            ("price_cache",  "_ensure_table"),
        )

        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"no_forward_20d_gap_report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "no_forward_20d_gap_report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            stack.enter_context(patch.object(
                cli, "_compute_breakdown",
                return_value=_FAKE_BREAKDOWN_ALL_FOUR,
            ))
            # The new loader walks the events archive and calls the
            # diagnostics classifiers, which reach into ``price_cache``
            # via the hydrator.  Patch the loader so this contract
            # test can stay focused on the report's own seams without
            # relying on hydration-side internal details.
            stack.enter_context(patch.object(
                cli, "_load_auto_adjust_mismatch_details",
                return_value=[],
            ))
            rc, output = _run_cli(["--json"])

        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_no_forward_20d"], 4)


# ---------------------------------------------------------------------------
# Auto-adjust mismatch details — focused per-row enrichment for the
# ``auto_adjust_mismatch_for_20d`` examples.  These tests cover the
# new diagnostic block introduced for the live archive's 4 mismatched
# rows: per-row event_date, available auto_adjust flags, cache max
# date per flag, and a fixed recommended_action label.
# ---------------------------------------------------------------------------


_FOUR_AUTO_ADJUST_BREAKDOWN = {
    "available": True,
    "total_no_forward_20d": 4,
    "counts": {
        "event_too_recent_for_20d":     0,
        "auto_adjust_mismatch_for_20d": 4,
        "cache_max_before_20d_horizon": 0,
        "likely_delisted_or_sparse":    0,
    },
    "examples": [
        _example(101, "AAPL", "auto_adjust_mismatch_for_20d"),
        _example(102, "MSFT", "auto_adjust_mismatch_for_20d"),
        _example(103, "GOOG", "auto_adjust_mismatch_for_20d"),
        _example(104, "TSLA", "auto_adjust_mismatch_for_20d"),
    ],
}


def _fake_detail(event_id, symbol, *, event_date, flags, cache_max):
    return {
        "event_id":                    event_id,
        "event_date":                  event_date,
        "symbol":                      symbol,
        "available_auto_adjust_flags": flags,
        "cache_max_per_flag":          cache_max,
        "recommended_action":
            "refresh_unadjusted_cache_to_align_hydrator",
    }


_FOUR_FAKE_DETAILS = [
    _fake_detail(
        101, "AAPL", event_date="2026-04-15",
        flags=[0, 1],
        cache_max={"0": "2026-04-14", "1": "2026-05-06"},
    ),
    _fake_detail(
        102, "MSFT", event_date="2026-04-16",
        flags=[0, 1],
        cache_max={"0": "2026-04-14", "1": "2026-05-06"},
    ),
    _fake_detail(
        103, "GOOG", event_date="2026-04-17",
        flags=[1],
        cache_max={"1": "2026-05-06"},
    ),
    _fake_detail(
        104, "TSLA", event_date="2026-04-18",
        flags=[0, 1],
        cache_max={"0": "2026-04-14", "1": "2026-05-06"},
    ),
]


class TestAutoAdjustMismatchDetailsShape(unittest.TestCase):
    def _run_with_details(self, breakdown, details, *, argv=("--json",)):
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown), \
             patch.object(cli, "_load_auto_adjust_mismatch_details",
                          return_value=list(details)):
            rc, output = _run_cli(list(argv))
        return rc, output

    def test_top_level_carries_details_key(self) -> None:
        rc, output = self._run_with_details(
            _FOUR_AUTO_ADJUST_BREAKDOWN, _FOUR_FAKE_DETAILS,
        )
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertIn("auto_adjust_mismatch_details", body)
        self.assertIsInstance(body["auto_adjust_mismatch_details"], list)

    def test_each_detail_carries_required_fields(self) -> None:
        _, output = self._run_with_details(
            _FOUR_AUTO_ADJUST_BREAKDOWN, _FOUR_FAKE_DETAILS,
        )
        body = json.loads(output)
        details = body["auto_adjust_mismatch_details"]
        self.assertEqual(len(details), 4)
        for detail in details:
            for key in _DETAIL_KEYS:
                self.assertIn(key, detail, f"detail missing field: {key}")

    def test_recommended_action_is_fixed_label(self) -> None:
        _, output = self._run_with_details(
            _FOUR_AUTO_ADJUST_BREAKDOWN, _FOUR_FAKE_DETAILS,
        )
        body = json.loads(output)
        actions = {d["recommended_action"]
                   for d in body["auto_adjust_mismatch_details"]}
        self.assertEqual(
            actions, {"refresh_unadjusted_cache_to_align_hydrator"},
        )

    def test_event_date_symbol_and_flags_round_trip(self) -> None:
        _, output = self._run_with_details(
            _FOUR_AUTO_ADJUST_BREAKDOWN, _FOUR_FAKE_DETAILS,
        )
        body = json.loads(output)
        details = body["auto_adjust_mismatch_details"]
        by_id = {d["event_id"]: d for d in details}
        self.assertEqual(by_id[101]["symbol"],     "AAPL")
        self.assertEqual(by_id[101]["event_date"], "2026-04-15")
        self.assertEqual(by_id[101]["available_auto_adjust_flags"], [0, 1])
        self.assertEqual(
            by_id[101]["cache_max_per_flag"],
            {"0": "2026-04-14", "1": "2026-05-06"},
        )
        # GOOG row only has the auto_adjust=1 flag, mirroring the
        # mismatch's defining condition.
        self.assertEqual(by_id[103]["available_auto_adjust_flags"], [1])
        self.assertEqual(
            by_id[103]["cache_max_per_flag"], {"1": "2026-05-06"},
        )

    def test_loader_returning_empty_yields_empty_details(self) -> None:
        # The loader walks the events archive independently of the
        # breakdown's example list — pin the empty-loader path here so
        # the payload shape stays well-defined when the archive has no
        # mismatches.
        breakdown = {
            "available":            True,
            "total_no_forward_20d": 0,
            "counts": {
                "event_too_recent_for_20d":     0,
                "auto_adjust_mismatch_for_20d": 0,
                "cache_max_before_20d_horizon": 0,
                "likely_delisted_or_sparse":    0,
            },
            "examples": [],
        }
        with patch.object(cli, "_compute_breakdown",
                          return_value=breakdown), \
             patch.object(cli, "_load_auto_adjust_mismatch_details",
                          return_value=[]):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["auto_adjust_mismatch_details"], [])

    def test_existing_top_level_keys_remain_backward_compatible(self) -> None:
        # The new key must not displace any existing key.
        _, output = self._run_with_details(
            _FOUR_AUTO_ADJUST_BREAKDOWN, _FOUR_FAKE_DETAILS,
        )
        body = json.loads(output)
        for key in (
            "total_no_forward_20d",
            "too_recent",
            "auto_adjust_mismatch",
            "cache_window_gap",
            "likely_delisted_or_sparse",
            "refreshable_gap_examples",
            "non_refreshable_examples",
            "recommended_next_action",
        ):
            self.assertIn(
                key, body,
                f"existing top-level key dropped: {key}",
            )


class TestAutoAdjustMismatchDetailsLimit(unittest.TestCase):
    def test_limit_truncates_details(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FOUR_AUTO_ADJUST_BREAKDOWN), \
             patch.object(cli, "_load_auto_adjust_mismatch_details",
                          return_value=list(_FOUR_FAKE_DETAILS)):
            _, output = _run_cli(["--json", "--limit", "2"])
        body = json.loads(output)
        self.assertEqual(len(body["auto_adjust_mismatch_details"]), 2)
        # Order is preserved across truncation.
        self.assertEqual(
            [d["event_id"] for d in body["auto_adjust_mismatch_details"]],
            [101, 102],
        )

    def test_limit_above_supply_returns_full_list(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FOUR_AUTO_ADJUST_BREAKDOWN), \
             patch.object(cli, "_load_auto_adjust_mismatch_details",
                          return_value=list(_FOUR_FAKE_DETAILS)):
            _, output = _run_cli(["--json", "--limit", "100"])
        body = json.loads(output)
        self.assertEqual(len(body["auto_adjust_mismatch_details"]), 4)


class TestAutoAdjustMismatchDetailsTextRendering(unittest.TestCase):
    def test_text_output_includes_detail_section(self) -> None:
        with patch.object(cli, "_compute_breakdown",
                          return_value=_FOUR_AUTO_ADJUST_BREAKDOWN), \
             patch.object(cli, "_load_auto_adjust_mismatch_details",
                          return_value=list(_FOUR_FAKE_DETAILS)):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("Auto-adjust mismatch details", output)
        # Per-row rendering surfaces the symbol + per-flag cache max.
        self.assertIn("symbol=AAPL", output)
        self.assertIn("aa=0->2026-04-14", output)
        self.assertIn("aa=1->2026-05-06", output)
        self.assertIn("refresh_unadjusted_cache_to_align_hydrator", output)


# ---------------------------------------------------------------------------
# Real loader against a temp SQLite fixture — no provider, no live DB.
# ---------------------------------------------------------------------------


class TestAutoAdjustMismatchDetailsLoader(unittest.TestCase):
    """Exercise ``_load_auto_adjust_mismatch_details`` against a temp
    SQLite fixture.  The diagnostics classifiers
    (``_classify_blocker_for_ticker`` /
    ``_classify_no_forward_20d_subreason``) are patched so the test
    pins the loader's data flow (event walk → SQL → per-flag map
    assembly) without depending on the heavy hydrator machinery.
    """

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_nf20_aa_loader_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed_event(
        self,
        *,
        headline: str,
        event_date,
        tickers: list,
    ) -> int:
        record = {
            "headline":     headline,
            "stage":        "realized",
            "persistence":  "medium",
            "event_date":   event_date,
            "market_tickers": [{"symbol": s} for s in tickers],
        }
        db.save_event(record)
        with sqlite3.connect(self._tmp) as conn:
            row = conn.execute(
                "SELECT id FROM events WHERE headline = ? "
                "ORDER BY id DESC LIMIT 1",
                (headline,),
            ).fetchone()
        return int(row[0])

    def _seed_cache(
        self, *, ticker: str, date_iso: str, flag: int,
    ) -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker.upper(), date_iso, 100.0, 5_000_000.0, flag,
                 "2026-05-06T12:00:00+00:00"),
            )
            conn.commit()

    @staticmethod
    def _classifier_patches(
        *,
        blocker_reason: str = "no_forward_20d_close",
        sub_reason: str = "auto_adjust_mismatch_for_20d",
    ):
        return (
            patch(
                "routes.diagnostics._classify_blocker_for_ticker",
                return_value=blocker_reason,
            ),
            patch(
                "routes.diagnostics._classify_no_forward_20d_subreason",
                return_value=sub_reason,
            ),
        )

    def test_empty_db_returns_empty_list(self) -> None:
        self.assertEqual(cli._load_auto_adjust_mismatch_details(), [])

    def test_loader_surfaces_every_mismatch_no_example_cap(self) -> None:
        # Seed 3 mismatch events.  The breakdown's 10-example cap could
        # in principle hide some of these; the loader must surface all
        # of them.
        eids: list[int] = []
        for i in range(3):
            eids.append(self._seed_event(
                headline=f"aa-mismatch every {i}",
                event_date="2026-01-10",
                tickers=[f"TKR{i}"],
            ))
            self._seed_cache(ticker=f"TKR{i}", date_iso="2026-01-15", flag=0)
            self._seed_cache(ticker=f"TKR{i}", date_iso="2026-02-15", flag=1)

        cls_patch, sub_patch = self._classifier_patches()
        with cls_patch, sub_patch:
            details = cli._load_auto_adjust_mismatch_details()

        self.assertEqual(len(details), 3)
        self.assertEqual(
            sorted(d["event_id"] for d in details), sorted(eids),
        )
        for detail in details:
            self.assertEqual(
                detail["recommended_action"],
                "refresh_unadjusted_cache_to_align_hydrator",
            )

    def test_loader_resolves_event_date_symbol_and_per_flag_max(self) -> None:
        eid = self._seed_event(
            headline="aa-mismatch fields",
            event_date="2026-04-15",
            tickers=["AAPL"],
        )
        # aa=0 newest = 2026-04-14 (before 20d horizon).
        # aa=1 newest = 2026-05-06 (covers 20d horizon).
        self._seed_cache(ticker="AAPL", date_iso="2026-04-14", flag=0)
        self._seed_cache(ticker="AAPL", date_iso="2026-04-10", flag=0)
        self._seed_cache(ticker="AAPL", date_iso="2026-05-06", flag=1)
        self._seed_cache(ticker="AAPL", date_iso="2026-04-30", flag=1)

        cls_patch, sub_patch = self._classifier_patches()
        with cls_patch, sub_patch:
            details = cli._load_auto_adjust_mismatch_details()

        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(d["event_id"],   eid)
        self.assertEqual(d["event_date"], "2026-04-15")
        self.assertEqual(d["symbol"],     "AAPL")
        self.assertEqual(d["available_auto_adjust_flags"], [0, 1])
        self.assertEqual(
            d["cache_max_per_flag"],
            {"0": "2026-04-14", "1": "2026-05-06"},
        )

    def test_loader_excludes_non_no_forward_20d_close_rows(self) -> None:
        # The classifier returns no_forward_20d_close for MATCH only;
        # NONMATCH gets a different reason and must be excluded.
        eid_match = self._seed_event(
            headline="aa-mismatch match",
            event_date="2026-04-15",
            tickers=["MATCH"],
        )
        self._seed_event(
            headline="aa-mismatch nonmatch",
            event_date="2026-04-15",
            tickers=["NONMATCH"],
        )
        self._seed_cache(ticker="MATCH",    date_iso="2026-04-14", flag=0)
        self._seed_cache(ticker="MATCH",    date_iso="2026-05-06", flag=1)
        self._seed_cache(ticker="NONMATCH", date_iso="2026-04-14", flag=0)
        self._seed_cache(ticker="NONMATCH", date_iso="2026-05-06", flag=1)

        def _classifier(saved_ticker, event_date):
            sym = saved_ticker.get("symbol") if isinstance(saved_ticker, dict) else None
            if sym == "MATCH":
                return "no_forward_20d_close"
            return "no_forward_5d_close"

        with patch("routes.diagnostics._classify_blocker_for_ticker",
                   side_effect=_classifier), \
             patch("routes.diagnostics._classify_no_forward_20d_subreason",
                   return_value="auto_adjust_mismatch_for_20d"):
            details = cli._load_auto_adjust_mismatch_details()

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["event_id"], eid_match)
        self.assertEqual(details[0]["symbol"],   "MATCH")

    def test_loader_excludes_other_subreasons(self) -> None:
        self._seed_event(
            headline="aa-mismatch cgap",
            event_date="2026-04-15",
            tickers=["CGAP"],
        )
        self._seed_cache(ticker="CGAP", date_iso="2026-04-14", flag=0)

        cls_patch, sub_patch = self._classifier_patches(
            sub_reason="cache_max_before_20d_horizon",
        )
        with cls_patch, sub_patch:
            details = cli._load_auto_adjust_mismatch_details()
        self.assertEqual(details, [])

    def test_loader_emits_blank_cache_when_ticker_uncached(self) -> None:
        eid = self._seed_event(
            headline="aa-mismatch nocache",
            event_date="2026-04-17",
            tickers=["UNKNOWN"],
        )
        # No price_cache rows for UNKNOWN.
        cls_patch, sub_patch = self._classifier_patches()
        with cls_patch, sub_patch:
            details = cli._load_auto_adjust_mismatch_details()

        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(d["event_id"], eid)
        self.assertEqual(d["available_auto_adjust_flags"], [])
        self.assertEqual(d["cache_max_per_flag"],          {})

    def test_loader_skips_rows_without_event_date(self) -> None:
        # Event with NULL event_date must be excluded before the
        # classifier ever runs — the breakdown does the same gating.
        record = {
            "headline":     "aa-mismatch nodate",
            "stage":        "realized",
            "persistence":  "medium",
            "event_date":   None,
            "market_tickers": [{"symbol": "AAPL"}],
        }
        db.save_event(record)
        self._seed_cache(ticker="AAPL", date_iso="2026-04-14", flag=0)

        cls_patch, sub_patch = self._classifier_patches()
        with cls_patch, sub_patch:
            details = cli._load_auto_adjust_mismatch_details()
        self.assertEqual(details, [])

    def test_loader_does_not_mutate_db(self) -> None:
        self._seed_event(
            headline="aa-mismatch nomut",
            event_date="2026-04-18",
            tickers=["GOOG"],
        )
        self._seed_cache(ticker="GOOG", date_iso="2026-05-06", flag=1)
        before = _snapshot_tables(self._tmp)
        cls_patch, sub_patch = self._classifier_patches()
        with cls_patch, sub_patch:
            for _ in range(3):
                cli._load_auto_adjust_mismatch_details()
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical across "
            "repeated loader runs",
        )


if __name__ == "__main__":
    unittest.main()
