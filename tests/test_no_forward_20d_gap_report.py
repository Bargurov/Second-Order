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
    "recommended_next_action",
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
            rc, output = _run_cli(["--json"])

        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_no_forward_20d"], 4)


if __name__ == "__main__":
    unittest.main()
