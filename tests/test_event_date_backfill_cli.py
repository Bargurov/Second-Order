"""Tests for ``scripts/event_date_backfill.py`` — CLI surface.

Patches the planner seam so tests don't depend on any live archive.
Pins:

  * ``--json`` emits structured top-level keys.
  * Default text output contains the readable summary lines.
  * ``--db-path`` forwards to the planner.
  * ``--apply`` is permanently rejected by argparse — the documented
    write combo is ``--write --confirm``.  The full ``--write`` /
    ``--confirm`` contract is pinned in
    ``tests/test_event_date_backfill_write_contract.py`` (gating) and
    ``tests/test_event_date_backfill_apply.py`` (writer behavior).
  * No provider, yfinance, market_check, market_data, price_cache,
    LLM, or FastAPI seam is invoked or imported by the dry-run path.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import builtins
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import event_date_backfill as cli  # noqa: E402


_FAKE_PLAN = {
    "total_candidates":           3,
    "events_with_market_tickers": 2,
    "ticker_rows_blocked":        4,
    "proposed_updates": [
        {
            "event_id":            1,
            "headline":            "Plan one headline",
            "timestamp":           "2026-04-15T13:30:00",
            "proposed_event_date": "2026-04-15",
            "ticker_count":        2,
            "tickers":             ["AAPL", "MSFT"],
        },
        {
            "event_id":            2,
            "headline":            "Plan two headline",
            "timestamp":           "2026-04-16T09:00:00",
            "proposed_event_date": "2026-04-16",
            "ticker_count":        1,
            "tickers":             ["GOOG"],
        },
    ],
    "skipped_counts": {"timestamp_unparseable": 1},
    "confidence_note": "stub confidence note",
}


_EMPTY_PLAN = {
    "total_candidates":           0,
    "events_with_market_tickers": 0,
    "ticker_rows_blocked":        0,
    "proposed_updates":           [],
    "skipped_counts":             {"timestamp_unparseable": 0},
    "confidence_note":            "stub confidence note",
}


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


class TestCliJSON(unittest.TestCase):
    def test_json_emits_top_level_keys(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in (
            "total_candidates",
            "events_with_market_tickers",
            "ticker_rows_blocked",
            "proposed_updates_count",
            "proposed_updates",
            "skipped_counts",
            "confidence_note",
        ):
            self.assertIn(key, body, f"missing JSON key: {key}")

    def test_json_proposed_updates_count_matches_list_length(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["proposed_updates_count"], 2)
        self.assertEqual(len(body["proposed_updates"]), 2)

    def test_json_carries_skipped_counts_and_note(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["skipped_counts"], {"timestamp_unparseable": 1})
        self.assertEqual(body["confidence_note"], "stub confidence note")

    def test_json_empty_plan_serialises(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_EMPTY_PLAN):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_candidates"],       0)
        self.assertEqual(body["proposed_updates_count"], 0)
        self.assertEqual(body["proposed_updates"],       [])


class TestCliText(unittest.TestCase):
    def test_text_lines_carry_each_count(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        for needle in (
            "Total candidates",
            "Events with market tickers",
            "Ticker rows blocked",
            "Proposed updates",
            "Skipped counts",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_text_surfaces_first_proposed_update(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            _, output = _run_cli([])
        self.assertIn("Plan one headline", output)
        self.assertIn("2026-04-15", output)

    def test_text_surfaces_skipped_counts(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            _, output = _run_cli([])
        self.assertIn("timestamp_unparseable", output)

    def test_text_handles_empty_plan(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_EMPTY_PLAN):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("Total candidates", output)


class TestCliDbPathForwarding(unittest.TestCase):
    def test_db_path_passes_through_to_planner(self) -> None:
        seen: dict = {}

        def fake_plan(*, db_path=None):
            seen["db_path"] = db_path
            return _FAKE_PLAN

        with patch.object(cli, "plan_event_date_backfill",
                          side_effect=fake_plan):
            rc, _ = _run_cli(["--db-path", "/tmp/snap.db", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["db_path"], "/tmp/snap.db")

    def test_db_path_default_is_none(self) -> None:
        seen: dict = {}

        def fake_plan(*, db_path=None):
            seen["db_path"] = db_path
            return _FAKE_PLAN

        with patch.object(cli, "plan_event_date_backfill",
                          side_effect=fake_plan):
            rc, _ = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        self.assertIsNone(seen["db_path"])


class TestCliRejectsApplyFlag(unittest.TestCase):
    """``--apply`` is a permanent typo guard.  The documented write
    combo is ``--write --confirm`` — see the write contract for the
    full --write/--confirm gating tests."""

    def test_apply_flag_not_accepted(self) -> None:
        with patch.object(cli, "plan_event_date_backfill",
                          return_value=_FAKE_PLAN):
            with patch("sys.stderr", new_callable=StringIO):
                with self.assertRaises(SystemExit) as cm:
                    _run_cli(["--apply"])
        self.assertEqual(cm.exception.code, 2)


class TestCliNoProviderSeams(unittest.TestCase):
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
                        f"event_date_backfill CLI must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "event_date_backfill CLI must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            stack.enter_context(patch.object(
                cli, "plan_event_date_backfill",
                return_value=_FAKE_PLAN,
            ))
            rc, output = _run_cli(["--json"])

        self.assertEqual(rc, 0)
        body = json.loads(output)
        # Sanity: real composed output, not a fallback.
        self.assertEqual(body["total_candidates"], 3)


class TestCliNoFastAPISeams(unittest.TestCase):
    def test_cli_module_does_not_carry_router_or_app(self) -> None:
        # Regression guard: the CLI must not host FastAPI symbols.
        self.assertFalse(hasattr(cli, "app"))
        self.assertFalse(hasattr(cli, "router"))

    def test_cli_does_not_import_routes_diagnostics(self) -> None:
        # Even when the CLI runs, it must not pull in the FastAPI route
        # surface — that route already exists, but importing it would
        # boot the app and the LLM-config path.
        real_import = builtins.__import__

        def guard_import(name, globals=None, locals=None, fromlist=(),
                         level=0):
            if name == "routes.diagnostics":
                raise AssertionError(
                    "event_date_backfill CLI must not import "
                    "routes.diagnostics",
                )
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guard_import):
            with patch.object(cli, "plan_event_date_backfill",
                              return_value=_FAKE_PLAN):
                _run_cli(["--json"])


if __name__ == "__main__":
    unittest.main()
