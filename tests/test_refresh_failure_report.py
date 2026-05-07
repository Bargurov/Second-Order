"""Tests for ``scripts/refresh_failure_report.py``.

The parser is fed ``refresh_price_cache.py`` JSON payloads (or just
the ``errors[]`` list) and asserts the classifier:

  * Bucket assignment for the four categories
    (``operational_error`` / ``invalid_ticker`` /
    ``empty_provider_result`` / ``unknown``).
  * Affected-ticker dedup, upper-case, sort.
  * Examples carry ``{event_id, symbol, error, category}``, capped at 10.
  * Recommendation tracks the dominant bucket.
  * CLI accepts ``--input`` and stdin, supports ``--json`` and text.
  * Module never imports a provider/yfinance/LLM/DB/FastAPI seam.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import refresh_failure_report as cli  # noqa: E402


_TOP_KEYS = (
    "ok",
    "total_errors",
    "grouped_counts",
    "affected_tickers",
    "examples",
    "recommended_next_action",
)

_GROUP_KEYS = (
    "operational_error",
    "invalid_ticker",
    "empty_provider_result",
    "unknown",
)


def _err(symbol, error_text, *, event_id=None,
         interval_start=None, interval_end=None):
    return {
        "event_id":       event_id,
        "symbol":         symbol,
        "interval_start": interval_start,
        "interval_end":   interval_end,
        "error":          error_text,
    }


# ---------------------------------------------------------------------------
# parse_failures — pure function
# ---------------------------------------------------------------------------


class TestParseEmpty(unittest.TestCase):
    def test_empty_errors_list_yields_ok_true(self) -> None:
        report = cli.parse_failures({"errors": []})
        self.assertTrue(report["ok"])
        self.assertEqual(report["total_errors"], 0)
        for cat in _GROUP_KEYS:
            self.assertEqual(report["grouped_counts"][cat], 0,
                             f"{cat} should be zero")
        self.assertEqual(report["affected_tickers"], [])
        self.assertEqual(report["examples"], [])

    def test_missing_errors_key_treated_as_empty(self) -> None:
        report = cli.parse_failures({})
        self.assertTrue(report["ok"])
        self.assertEqual(report["total_errors"], 0)

    def test_payload_not_a_dict_treated_as_empty(self) -> None:
        report = cli.parse_failures(None)
        self.assertTrue(report["ok"])
        self.assertEqual(report["total_errors"], 0)
        report = cli.parse_failures("garbage")
        self.assertTrue(report["ok"])
        self.assertEqual(report["total_errors"], 0)

    def test_errors_value_not_a_list_treated_as_empty(self) -> None:
        report = cli.parse_failures({"errors": "boom"})
        self.assertEqual(report["total_errors"], 0)


class TestParseClassification(unittest.TestCase):
    def test_operational_error_unable_to_open(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("AAPL", "OperationalError: unable to open database file"),
        ]})
        self.assertFalse(report["ok"])
        self.assertEqual(report["total_errors"], 1)
        self.assertEqual(report["grouped_counts"]["operational_error"], 1)

    def test_operational_error_generic_message(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("AAPL",
                 "OperationalError: database is locked"),
        ]})
        self.assertEqual(report["grouped_counts"]["operational_error"], 1)

    def test_invalid_ticker_delisted_message(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("POT",
                 "Exception: POT: No data found, symbol may be delisted"),
        ]})
        self.assertEqual(report["grouped_counts"]["invalid_ticker"], 1)
        self.assertEqual(report["grouped_counts"]["empty_provider_result"], 0)

    def test_invalid_ticker_no_longer_exists_message(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("XYZ",
                 "RuntimeError: ticker XYZ no longer exists"),
        ]})
        self.assertEqual(report["grouped_counts"]["invalid_ticker"], 1)

    def test_empty_provider_result_no_data(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("ABC", "ValueError: no data returned for ABC"),
        ]})
        self.assertEqual(report["grouped_counts"]["empty_provider_result"], 1)
        self.assertEqual(report["grouped_counts"]["invalid_ticker"], 0)

    def test_empty_provider_result_empty_dataframe(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("DEF", "RuntimeError: empty dataframe from provider"),
        ]})
        self.assertEqual(report["grouped_counts"]["empty_provider_result"], 1)

    def test_unknown_error_falls_through(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("ZZZ", "ConnectionError: timed out"),
        ]})
        self.assertEqual(report["grouped_counts"]["unknown"], 1)

    def test_classification_is_case_insensitive(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("A", "operationalerror: lowercase"),
            _err("B", "ABC: SYMBOL MAY BE DELISTED"),
        ]})
        self.assertEqual(report["grouped_counts"]["operational_error"], 1)
        self.assertEqual(report["grouped_counts"]["invalid_ticker"], 1)


class TestAffectedTickers(unittest.TestCase):
    def test_unique_symbols_sorted_uppercase(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("tsla", "OperationalError: x"),
            _err("AAPL", "OperationalError: x"),
            _err("tsla", "OperationalError: y"),
        ]})
        self.assertEqual(report["affected_tickers"], ["AAPL", "TSLA"])

    def test_null_and_empty_symbols_excluded(self) -> None:
        report = cli.parse_failures({"errors": [
            _err(None,   "OperationalError: preflight"),
            _err("",     "OperationalError: empty"),
            _err("AAPL", "OperationalError: real"),
        ]})
        self.assertEqual(report["affected_tickers"], ["AAPL"])


class TestExamples(unittest.TestCase):
    def test_examples_carry_required_fields(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("AAPL",
                 "OperationalError: x", event_id=7),
        ]})
        self.assertEqual(len(report["examples"]), 1)
        ex = report["examples"][0]
        for key in ("event_id", "symbol", "error", "category"):
            self.assertIn(key, ex, f"example missing field: {key}")
        self.assertEqual(ex["event_id"], 7)
        self.assertEqual(ex["symbol"], "AAPL")
        self.assertEqual(ex["category"], "operational_error")

    def test_examples_capped_at_10(self) -> None:
        errors = [
            _err(f"X{i}", "OperationalError: x") for i in range(15)
        ]
        report = cli.parse_failures({"errors": errors})
        self.assertEqual(report["total_errors"], 15)
        self.assertEqual(len(report["examples"]), 10)

    def test_examples_preserve_input_order(self) -> None:
        errors = [
            _err("A", "OperationalError: a"),
            _err("B", "Exception: B: symbol may be delisted"),
            _err("C", "ConnectionError: timed out"),
        ]
        report = cli.parse_failures({"errors": errors})
        self.assertEqual([e["symbol"] for e in report["examples"]],
                         ["A", "B", "C"])


class TestRecommendation(unittest.TestCase):
    def test_no_errors_recommendation_says_success(self) -> None:
        report = cli.parse_failures({"errors": []})
        self.assertIn("succeeded",
                      report["recommended_next_action"].lower())

    def test_operational_error_dominant_drives_action(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("A", "OperationalError: x"),
            _err("B", "OperationalError: y"),
            _err("C", "ConnectionError: timed out"),
        ]})
        action = report["recommended_next_action"].lower()
        self.assertIn("operational", action)

    def test_invalid_ticker_dominant_drives_action(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("X", "Exception: X: symbol may be delisted"),
            _err("Y", "Exception: Y: symbol may be delisted"),
            _err("Z", "ConnectionError: timed out"),
        ]})
        action = report["recommended_next_action"].lower()
        self.assertTrue(
            "delisted" in action or "invalid" in action,
            f"expected delisted/invalid hint, got: {action}",
        )

    def test_empty_provider_dominant_drives_action(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("A", "ValueError: no data returned"),
            _err("B", "ValueError: no data returned"),
            _err("C", "ConnectionError: timed out"),
        ]})
        action = report["recommended_next_action"].lower()
        self.assertIn("empty", action)


class TestNonDictErrorsIgnored(unittest.TestCase):
    def test_non_dict_entries_skipped(self) -> None:
        report = cli.parse_failures({"errors": [
            _err("AAPL", "OperationalError: x"),
            "not-a-dict",
            42,
            None,
        ]})
        self.assertEqual(report["total_errors"], 1)
        self.assertEqual(report["affected_tickers"], ["AAPL"])


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _run_cli(argv, *, stdin_text=""):
    out = StringIO()
    rc = cli.main(argv, out=out, stdin=StringIO(stdin_text))
    return rc, out.getvalue()


_FIXTURE_PAYLOAD = {
    "errors": [
        {"event_id": 1, "symbol": "AAPL",
         "error": "OperationalError: unable to open database file"},
        {"event_id": 2, "symbol": "POT",
         "error": "Exception: POT: No data found, symbol may be delisted"},
        {"event_id": 3, "symbol": "ABC",
         "error": "ValueError: no data returned for ABC"},
        {"event_id": 4, "symbol": "ZZZ",
         "error": "ConnectionError: timed out"},
    ]
}


class TestCliInputFile(unittest.TestCase):
    def test_reads_payload_from_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json",
        ) as f:
            json.dump(_FIXTURE_PAYLOAD, f)
            path = f.name
        try:
            rc, output = _run_cli(["--input", path, "--json"])
        finally:
            try:
                os.unlink(path)
            except (OSError, PermissionError):
                pass
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_errors"], 4)
        self.assertEqual(body["grouped_counts"]["operational_error"],     1)
        self.assertEqual(body["grouped_counts"]["invalid_ticker"],        1)
        self.assertEqual(body["grouped_counts"]["empty_provider_result"], 1)
        self.assertEqual(body["grouped_counts"]["unknown"],               1)


class TestCliStdin(unittest.TestCase):
    def test_reads_payload_from_stdin_when_no_input(self) -> None:
        rc, output = _run_cli(
            ["--json"], stdin_text=json.dumps(_FIXTURE_PAYLOAD),
        )
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_errors"], 4)
        self.assertEqual(set(body["affected_tickers"]),
                         {"AAPL", "POT", "ABC", "ZZZ"})


class TestCliJSONShape(unittest.TestCase):
    def test_json_top_level_keys_present(self) -> None:
        _, output = _run_cli(
            ["--json"], stdin_text=json.dumps(_FIXTURE_PAYLOAD),
        )
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing JSON key: {key}")
        for cat in _GROUP_KEYS:
            self.assertIn(cat, body["grouped_counts"])


class TestCliText(unittest.TestCase):
    def test_text_lists_categories_and_tickers(self) -> None:
        _, output = _run_cli(
            [], stdin_text=json.dumps(_FIXTURE_PAYLOAD),
        )
        for needle in (
            "Total errors",
            "operational_error",
            "invalid_ticker",
            "empty_provider_result",
            "unknown",
            "AAPL",
            "POT",
        ):
            self.assertIn(needle, output, f"missing line/value: {needle}")

    def test_text_says_no_errors_on_clean_input(self) -> None:
        _, output = _run_cli([], stdin_text=json.dumps({"errors": []}))
        self.assertIn("0", output)
        self.assertIn("succeeded", output.lower())


class TestCliErrorsListAccepted(unittest.TestCase):
    """Tolerate raw ``errors`` list at the top level — useful when a
    user pipes ``jq '.errors' refresh.json | refresh_failure_report.py``."""

    def test_accepts_top_level_list(self) -> None:
        rc, output = _run_cli(
            ["--json"],
            stdin_text=json.dumps(_FIXTURE_PAYLOAD["errors"]),
        )
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_errors"], 4)


class TestCliInvalidJSON(unittest.TestCase):
    def test_invalid_json_returns_nonzero(self) -> None:
        with patch("sys.stderr", new_callable=StringIO):
            rc, _ = _run_cli([], stdin_text="not-json")
        self.assertNotEqual(rc, 0)


class TestNoProviderSeams(unittest.TestCase):
    """Module imports must NOT pull in any provider/yfinance/LLM/DB or
    FastAPI seam — the parser is a pure stdlib transform."""

    def test_module_does_not_carry_seams(self) -> None:
        for forbidden in (
            "fastapi", "router", "app",
            "yfinance", "market_check", "market_data",
            "price_cache", "anthropic", "openai",
        ):
            self.assertFalse(
                hasattr(cli, forbidden),
                f"cli module unexpectedly carries '{forbidden}'",
            )

    def test_no_provider_seam_invoked_during_parse(self) -> None:
        from contextlib import ExitStack
        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "market_check"),
            ("market_data",  "get_provider"),
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
                        f"refresh_failure_report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "refresh_failure_report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            rc, _ = _run_cli(
                ["--json"], stdin_text=json.dumps(_FIXTURE_PAYLOAD),
            )
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
