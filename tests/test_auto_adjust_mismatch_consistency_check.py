"""Tests for ``scripts/auto_adjust_mismatch_consistency_check.py`` —
read-only consistency check that audits the
``auto_adjust_mismatch_for_20d`` count against two independent paths:

  * ``no_forward_20d_gap_report.auto_adjust_mismatch`` — derived from
    ``routes.diagnostics._compute_no_forward_20d_breakdown`` (SQL
    traversal #1).
  * ``auto_adjust_mismatch_repair_preview.total_mismatches`` — derived
    from ``no_forward_20d_gap_report._load_auto_adjust_mismatch_details``
    (SQL traversal #2).

These two paths walk the events archive independently with the same
classifiers; their counts must agree.  The consistency check emits a
JSON payload ``{ok, mismatch_count, preview_count, repairable_count,
errors}`` so a runbook (or CI) can branch deterministically on the
``ok`` flag.

Pinned invariants:

  * Pure ``_compare(...)`` returns the 5-key payload.  Counts are
    nullable: ``None`` signals extraction failure, an int signals the
    actually-extracted value.
  * ``ok`` is True iff every count extracted, every count matched,
    and no errors accumulated.
  * Exit code is 0 on ``ok=True`` and 1 on ``ok=False``.
  * The two production seams (``_run_gap_report`` /
    ``_run_repair_preview``) invoke the underlying scripts in-process
    against ``StringIO`` and return the parsed JSON dict.
  * No DB writes, no provider call, no ``yfinance``, no LLM seam.
  * Read-only contract: repeated runs against a temp DB leave
    ``events`` + ``price_cache`` byte-identical.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402,F401  — pre-load so the lazy diagnostics
                                #  import inside the underlying scripts
                                #  never trips the api ↔
                                #  routes.diagnostics cycle.
import db  # noqa: E402
from scripts import (  # noqa: E402
    auto_adjust_mismatch_consistency_check as cli,
)


# ---------------------------------------------------------------------------
# Synthetic body builders — the two upstream scripts emit fully-formed
# JSON shapes; the helpers below produce minimal, valid stand-ins so the
# compare logic can be exercised without running the real archive.
# ---------------------------------------------------------------------------


def _gap_body(auto_adjust_mismatch: int = 0, **extras) -> dict:
    body = {
        "total_no_forward_20d":         max(int(auto_adjust_mismatch), 0),
        "too_recent":                   0,
        "auto_adjust_mismatch":         auto_adjust_mismatch,
        "cache_window_gap":             0,
        "likely_delisted_or_sparse":    0,
        "refreshable_gap_examples":     [],
        "non_refreshable_examples":     [],
        "auto_adjust_mismatch_details": [],
        "recommended_next_action":      "no_action_needed_no_gaps",
    }
    body.update(extras)
    return body


def _preview_body(
    total_mismatches: int = 0,
    repairable_count: int = 0,
    **extras,
) -> dict:
    body = {
        "total_mismatches":         total_mismatches,
        "repairable_count":         repairable_count,
        "non_repairable_count":     0,
        "counts_by_status":         {},
        "proposed_rows":            [],
        "recommended_next_action":  "no_action_needed_no_mismatches",
    }
    body.update(extras)
    return body


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Pure compare logic
# ---------------------------------------------------------------------------


class TestCompareMatchingCounts(unittest.TestCase):
    """When both upstream scripts agree on the auto_adjust_mismatch
    count, the check passes with no errors.
    """

    def test_zero_match_yields_ok_true_no_errors(self) -> None:
        result = cli._compare(_gap_body(0), _preview_body(0, 0))
        self.assertTrue(result["ok"])
        self.assertEqual(result["mismatch_count"],   0)
        self.assertEqual(result["preview_count"],    0)
        self.assertEqual(result["repairable_count"], 0)
        self.assertEqual(result["errors"], [])

    def test_nonzero_match_yields_ok_true_with_repairable_below_total(self) -> None:
        result = cli._compare(_gap_body(5), _preview_body(5, 3))
        self.assertTrue(result["ok"])
        self.assertEqual(result["mismatch_count"],   5)
        self.assertEqual(result["preview_count"],    5)
        self.assertEqual(result["repairable_count"], 3)
        self.assertEqual(result["errors"], [])

    def test_repairable_equal_to_total_is_legal(self) -> None:
        # Every mismatch is repairable — nothing to investigate.
        result = cli._compare(_gap_body(2), _preview_body(2, 2))
        self.assertTrue(result["ok"])

    def test_payload_has_exact_top_level_keys(self) -> None:
        result = cli._compare(_gap_body(0), _preview_body(0, 0))
        self.assertEqual(
            sorted(result.keys()),
            sorted([
                "ok", "mismatch_count", "preview_count",
                "repairable_count", "errors",
            ]),
        )


class TestCompareDivergence(unittest.TestCase):
    """Divergence between the gap-report count and the preview total
    means the two SQL traversals disagree — the check must fail loudly.
    """

    def test_count_divergence_yields_ok_false(self) -> None:
        result = cli._compare(_gap_body(5), _preview_body(7, 3))
        self.assertFalse(result["ok"])
        self.assertEqual(result["mismatch_count"], 5)
        self.assertEqual(result["preview_count"],  7)
        self.assertTrue(any("divergence" in e for e in result["errors"]))
        # Error message names both sides so the operator can tell which
        # path drifted.
        joined = " ".join(result["errors"])
        self.assertIn("5", joined)
        self.assertIn("7", joined)

    def test_synthetic_repairable_exceeding_total_is_rejected(self) -> None:
        # The production preview never emits this — repairable_count is
        # a partition of total_mismatches.  Pinned as defense-in-depth so
        # a future bug that breaks the partition tripwires here.
        result = cli._compare(_gap_body(5), _preview_body(5, 99))
        self.assertFalse(result["ok"])
        self.assertTrue(any("impossible" in e for e in result["errors"]))


class TestCompareInvalidShapes(unittest.TestCase):
    """When an upstream count is missing or malformed, the matching
    field is ``None`` and the check fails closed.
    """

    def test_gap_body_missing_count_yields_none(self) -> None:
        body = _gap_body()
        body.pop("auto_adjust_mismatch")
        result = cli._compare(body, _preview_body(0, 0))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["mismatch_count"])
        self.assertTrue(any("auto_adjust_mismatch" in e for e in result["errors"]))

    def test_preview_body_missing_total_yields_none(self) -> None:
        body = _preview_body()
        body.pop("total_mismatches")
        result = cli._compare(_gap_body(0), body)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["preview_count"])
        self.assertTrue(any("total_mismatches" in e for e in result["errors"]))

    def test_preview_body_missing_repairable_yields_none(self) -> None:
        body = _preview_body()
        body.pop("repairable_count")
        result = cli._compare(_gap_body(0), body)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["repairable_count"])

    def test_negative_count_rejected_as_invalid(self) -> None:
        result = cli._compare(_gap_body(-1), _preview_body(0, 0))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["mismatch_count"])

    def test_bool_count_rejected_even_though_int_subclass(self) -> None:
        body = _gap_body()
        body["auto_adjust_mismatch"] = True
        result = cli._compare(body, _preview_body(0, 0))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["mismatch_count"])

    def test_string_count_rejected(self) -> None:
        body = _preview_body()
        body["total_mismatches"] = "5"
        result = cli._compare(_gap_body(0), body)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["preview_count"])

    def test_none_gap_body_propagates_through_extraction(self) -> None:
        # When the upstream gap report failed to run, the seam returns
        # None and the compare layer must surface that as a missing
        # count, NOT silently coerce to zero.
        result = cli._compare(None, _preview_body(0, 0))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["mismatch_count"])

    def test_none_preview_body_propagates_through_extraction(self) -> None:
        result = cli._compare(_gap_body(0), None)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["preview_count"])
        self.assertIsNone(result["repairable_count"])

    def test_pre_errors_propagate_into_payload_errors(self) -> None:
        # When the wrapping main caught an exception while invoking an
        # upstream script, it passes the formatted error string through
        # ``errors_pre``.  Compare must include those verbatim.
        result = cli._compare(
            _gap_body(0),
            _preview_body(0, 0),
            errors_pre=["gap report failed: RuntimeError: simulated"],
        )
        self.assertFalse(result["ok"])
        self.assertIn(
            "gap report failed: RuntimeError: simulated",
            result["errors"],
        )


# ---------------------------------------------------------------------------
# CLI — JSON output, exit codes, default text rendering
# ---------------------------------------------------------------------------


class TestCLIJSONOutput(unittest.TestCase):
    """The ``--json`` flag emits the 5-key envelope the runbook reads."""

    def test_json_output_carries_required_keys(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(0)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(0, 0)):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in (
            "ok", "mismatch_count", "preview_count",
            "repairable_count", "errors",
        ):
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_json_output_reflects_match_state(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(3)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(3, 1)):
            rc, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(rc, 0)
        self.assertTrue(body["ok"])
        self.assertEqual(body["mismatch_count"],   3)
        self.assertEqual(body["preview_count"],    3)
        self.assertEqual(body["repairable_count"], 1)
        self.assertEqual(body["errors"], [])

    def test_json_output_reflects_divergence(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(3)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(5, 0)):
            rc, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertFalse(body["ok"])
        self.assertEqual(body["mismatch_count"], 3)
        self.assertEqual(body["preview_count"],  5)
        self.assertTrue(body["errors"])

    def test_json_output_serialises_none_counts_as_null(self) -> None:
        # When an upstream extraction fails the count is None.  JSON
        # serialisation must preserve that as ``null`` so a downstream
        # consumer can branch on the missing-extraction case.
        bad_gap = _gap_body()
        bad_gap.pop("auto_adjust_mismatch")
        with patch.object(cli, "_run_gap_report", return_value=bad_gap), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(0, 0)):
            _, output = _run_cli(["--json"])
        self.assertIn('"mismatch_count": null', output)


class TestCLIExitCode(unittest.TestCase):
    """Exit code mirrors the ``ok`` flag: 0 on pass, 1 on fail.  CI can
    hook on the exit code without parsing the JSON payload.
    """

    def test_exit_zero_when_counts_match(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(0)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(0, 0)):
            rc, _ = _run_cli(["--json"])
        self.assertEqual(rc, 0)

    def test_exit_one_when_counts_diverge(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(0)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(2, 0)):
            rc, _ = _run_cli(["--json"])
        self.assertEqual(rc, 1)

    def test_exit_one_when_upstream_extraction_fails(self) -> None:
        bad_gap = _gap_body()
        bad_gap["auto_adjust_mismatch"] = "broken"
        with patch.object(cli, "_run_gap_report", return_value=bad_gap), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(0, 0)):
            rc, _ = _run_cli(["--json"])
        self.assertEqual(rc, 1)


class TestCLIDefaultTextRendering(unittest.TestCase):
    """Default invocation (no ``--json``) emits a compact human-
    readable summary so an operator can read it without piping to jq.
    """

    def test_text_output_lists_pass_status_and_counts(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(2)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(2, 1)):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("OK", output)
        self.assertIn("mismatch_count", output)
        self.assertIn("preview_count",  output)
        self.assertIn("repairable_count", output)

    def test_text_output_renders_failure_with_error_lines(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(2)), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(5, 0)):
            rc, output = _run_cli([])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", output)
        self.assertIn("divergence", output)


# ---------------------------------------------------------------------------
# Upstream runner seams
# ---------------------------------------------------------------------------


class TestRunGapReport(unittest.TestCase):
    """``_run_gap_report`` invokes ``no_forward_20d_gap_report.main`` in
    process, captures the JSON output, and returns the parsed dict.  The
    test patches the underlying classifiers so the integration path is
    exercised without touching the real archive.
    """

    def test_returns_parsed_dict_with_auto_adjust_mismatch_key(self) -> None:
        from scripts import no_forward_20d_gap_report as gap_module
        empty_breakdown = {
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
        with patch.object(gap_module, "_compute_breakdown",
                          return_value=empty_breakdown), \
             patch.object(gap_module, "_load_auto_adjust_mismatch_details",
                          return_value=[]):
            body = cli._run_gap_report()
        self.assertIsInstance(body, dict)
        self.assertIn("auto_adjust_mismatch", body)
        self.assertEqual(body["auto_adjust_mismatch"], 0)

    def test_propagates_count_from_underlying_breakdown(self) -> None:
        from scripts import no_forward_20d_gap_report as gap_module
        breakdown = {
            "available": True,
            "total_no_forward_20d": 4,
            "counts": {
                "event_too_recent_for_20d":     0,
                "auto_adjust_mismatch_for_20d": 4,
                "cache_max_before_20d_horizon": 0,
                "likely_delisted_or_sparse":    0,
            },
            "examples": [],
        }
        with patch.object(gap_module, "_compute_breakdown",
                          return_value=breakdown), \
             patch.object(gap_module, "_load_auto_adjust_mismatch_details",
                          return_value=[]):
            body = cli._run_gap_report()
        self.assertEqual(body["auto_adjust_mismatch"], 4)


class TestRunRepairPreview(unittest.TestCase):
    """``_run_repair_preview`` invokes
    ``auto_adjust_mismatch_repair_preview.main`` in process, captures the
    JSON output, and returns the parsed dict.
    """

    def test_returns_parsed_dict_with_total_mismatches_key(self) -> None:
        from scripts import auto_adjust_mismatch_repair_preview as preview_module
        with patch.object(preview_module, "_load_auto_adjust_mismatch_details",
                          return_value=[]), \
             patch.object(preview_module, "_load_in_window_cache_rows",
                          return_value={}):
            body = cli._run_repair_preview()
        self.assertIsInstance(body, dict)
        self.assertIn("total_mismatches",  body)
        self.assertIn("repairable_count",  body)
        self.assertEqual(body["total_mismatches"],  0)
        self.assertEqual(body["repairable_count"],  0)


class TestRunnerExceptionHandling(unittest.TestCase):
    """When an upstream runner raises, the wrapping main converts the
    exception into a string entry in the payload's ``errors`` list and
    keeps going.  This is the most failure-prone runtime concern (a
    future schema change in either upstream script).
    """

    def test_gap_report_exception_appears_in_errors(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          side_effect=RuntimeError("synthetic gap failure")), \
             patch.object(cli, "_run_repair_preview",
                          return_value=_preview_body(0, 0)):
            rc, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(rc, 1)
        self.assertFalse(body["ok"])
        self.assertIsNone(body["mismatch_count"])
        self.assertTrue(any("synthetic gap failure" in e for e in body["errors"]))

    def test_repair_preview_exception_appears_in_errors(self) -> None:
        with patch.object(cli, "_run_gap_report",
                          return_value=_gap_body(0)), \
             patch.object(cli, "_run_repair_preview",
                          side_effect=RuntimeError("synthetic preview failure")):
            rc, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(rc, 1)
        self.assertFalse(body["ok"])
        self.assertIsNone(body["preview_count"])
        self.assertIsNone(body["repairable_count"])
        self.assertTrue(any(
            "synthetic preview failure" in e for e in body["errors"]
        ))


# ---------------------------------------------------------------------------
# No-mutation contract — temp DB, repeated runs, byte-identical
# ---------------------------------------------------------------------------


def _snapshot_tables(db_path: str) -> tuple[list, list]:
    with sqlite3.connect(db_path) as conn:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        try:
            cache = list(conn.execute(
                "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
                "FROM price_cache ORDER BY ticker, date, auto_adjust"
            ))
        except sqlite3.Error:
            cache = []
        return events, cache


class TestNoMutation(unittest.TestCase):
    """End-to-end read-only contract — let the real upstream scripts
    run against a temp SQLite fixture and confirm both tables are
    byte-identical before and after repeated CLI runs.
    """

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_consistency_{uuid.uuid4().hex}.db",
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

    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            rc, _ = _run_cli(["--json"])
            self.assertEqual(rc, 0)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical before and "
            "after repeated consistency-check runs",
        )


# ---------------------------------------------------------------------------
# No-provider invariant — no market_check / market_data / yfinance / LLM
# ---------------------------------------------------------------------------


class TestNoProviderCalls(unittest.TestCase):
    """The CLI must never call market_check, market_data, yfinance,
    fetch_daily_cached, or any LLM seam — this audit is read-only and
    must not flip into a paid path even in error scenarios."""

    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
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
                        f"consistency check must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "consistency check must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            stack.enter_context(patch.object(
                cli, "_run_gap_report", return_value=_gap_body(0),
            ))
            stack.enter_context(patch.object(
                cli, "_run_repair_preview",
                return_value=_preview_body(0, 0),
            ))
            rc, output = _run_cli(["--json"])

        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertTrue(body["ok"])


if __name__ == "__main__":
    unittest.main()
