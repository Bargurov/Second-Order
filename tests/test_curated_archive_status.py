"""Tests for ``scripts/curated_archive_status.py``.

Pin the contract:

* ``summarize_curated_archive(yaml_path)`` returns a dict with::

    {
      "total_events":          int,
      "valid_count":           int,
      "invalid_count":         int,
      "by_mechanism_family":   {family: count, ...},
      "date_range": {
        "min_event_date":      str | None,   # ISO YYYY-MM-DD
        "max_event_date":      str | None,
      },
      "ticker_coverage": {
        "primary_tickers":     [str, ...],   # sorted, deduplicated
        "benchmark_tickers":   [str, ...],
        "primary_ticker_count": int,
      },
      "missing_fields": {
        field_name: int, ...                 # how many events lack the field
      },
      "errors":                [str, ...],
      "warnings":              [str, ...],
    }

* The status report ALWAYS surfaces a 9-key envelope, even on empty
  input — operators get a stable JSON shape.
* ``by_mechanism_family`` counts every event (including invalid ones)
  that has a non-blank mechanism_family.
* ``ticker_coverage`` only counts validated events so an invalid
  ticker doesn't pollute the operator view.
* ``missing_fields`` aggregates required-field gaps across every
  event; the validator's per-event error list is the source of truth
  for the missing-field signal.
* Conservative wording — banned tokens (``proof``, ``alpha``,
  ``automatic``) absent from any text the report emits.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import curated_archive_status as cli  # noqa: E402


_REQUIRED_KEYS = (
    "total_events",
    "valid_count",
    "invalid_count",
    "by_mechanism_family",
    "date_range",
    "ticker_coverage",
    "missing_fields",
    "errors",
    "warnings",
)


_BANNED_WORDS = ("proof", "alpha", "automatic")


def _good_event(**overrides) -> dict:
    base = {
        "event_id":              1,
        "event_date":            "2026-04-01",
        "headline":              "h",
        "source_url":            "https://example.com/article",
        "primary_ticker":        "MS",
        "benchmark_ticker":      "SPY",
        "mechanism_family":      "bank_regulatory_capital_relief",
        "mechanism_description": "Capital relief.",
        "predicted_direction":   "up",
        "prediction_rationale":  "Section 23A exemption.",
        "curator_notes":         "n",
    }
    base.update(overrides)
    return base


def _patch_loader(events: list[dict], errors: list[str] | None = None):
    return patch.object(
        cli, "_load_curated_events",
        return_value=(list(events), list(errors or [])),
    )


def _summarize(events: list[dict], **kwargs) -> dict:
    with _patch_loader(events):
        return cli.summarize_curated_archive(
            yaml_path=kwargs.pop("yaml_path", "/x/curated.yaml"),
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_returns_dict_with_exactly_nine_keys(self) -> None:
        result = _summarize([])
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_empty_archive_returns_zero_aggregates(self) -> None:
        result = _summarize([])
        self.assertEqual(result["total_events"], 0)
        self.assertEqual(result["valid_count"], 0)
        self.assertEqual(result["invalid_count"], 0)
        self.assertEqual(result["by_mechanism_family"], {})
        self.assertIsNone(result["date_range"]["min_event_date"])
        self.assertIsNone(result["date_range"]["max_event_date"])
        self.assertEqual(result["ticker_coverage"]["primary_tickers"], [])


# ---------------------------------------------------------------------------
# Counts + mechanism_family aggregation
# ---------------------------------------------------------------------------


class TestMechanismFamilyAggregation(unittest.TestCase):
    def test_groups_by_mechanism_family(self) -> None:
        events = [
            _good_event(event_id=1, mechanism_family="supply_shock"),
            _good_event(event_id=2, mechanism_family="supply_shock"),
            _good_event(
                event_id=3, mechanism_family="bank_regulatory_capital_relief"),
        ]
        result = _summarize(events)
        self.assertEqual(
            result["by_mechanism_family"],
            {"supply_shock": 2, "bank_regulatory_capital_relief": 1},
        )

    def test_blank_mechanism_family_excluded_from_count(self) -> None:
        events = [
            _good_event(event_id=1, mechanism_family=""),
            _good_event(event_id=2, mechanism_family="supply_shock"),
        ]
        result = _summarize(events)
        self.assertEqual(result["by_mechanism_family"], {"supply_shock": 1})


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------


class TestDateRange(unittest.TestCase):
    def test_min_and_max_dates_returned_as_iso_strings(self) -> None:
        events = [
            _good_event(event_id=1, event_date="2026-04-01"),
            _good_event(event_id=2, event_date="2026-04-15"),
            _good_event(event_id=3, event_date="2026-04-08"),
        ]
        result = _summarize(events)
        self.assertEqual(result["date_range"]["min_event_date"], "2026-04-01")
        self.assertEqual(result["date_range"]["max_event_date"], "2026-04-15")

    def test_invalid_dates_skipped_from_range_computation(self) -> None:
        events = [
            _good_event(event_id=1, event_date="2026-04-01"),
            _good_event(event_id=2, event_date="bogus"),
        ]
        result = _summarize(events)
        # Range reflects only the parseable date.
        self.assertEqual(result["date_range"]["min_event_date"], "2026-04-01")
        self.assertEqual(result["date_range"]["max_event_date"], "2026-04-01")


# ---------------------------------------------------------------------------
# Ticker coverage
# ---------------------------------------------------------------------------


class TestTickerCoverage(unittest.TestCase):
    def test_lists_primary_and_benchmark_tickers_sorted_unique(self) -> None:
        events = [
            _good_event(event_id=1, primary_ticker="MS",
                        benchmark_ticker="SPY"),
            _good_event(event_id=2, primary_ticker="XOM",
                        benchmark_ticker="SPY"),
            _good_event(event_id=3, primary_ticker="MS",
                        benchmark_ticker="XLE"),
        ]
        result = _summarize(events)
        self.assertEqual(
            result["ticker_coverage"]["primary_tickers"], ["MS", "XOM"])
        self.assertEqual(
            result["ticker_coverage"]["benchmark_tickers"], ["SPY", "XLE"])
        self.assertEqual(
            result["ticker_coverage"]["primary_ticker_count"], 2)

    def test_blank_tickers_excluded_from_coverage(self) -> None:
        events = [
            _good_event(event_id=1, primary_ticker="",
                        benchmark_ticker="SPY"),
            _good_event(event_id=2, primary_ticker="MS",
                        benchmark_ticker=""),
        ]
        result = _summarize(events)
        self.assertEqual(
            result["ticker_coverage"]["primary_tickers"], ["MS"])
        self.assertEqual(
            result["ticker_coverage"]["benchmark_tickers"], ["SPY"])


# ---------------------------------------------------------------------------
# Missing fields aggregate
# ---------------------------------------------------------------------------


class TestMissingFields(unittest.TestCase):
    def test_aggregates_count_per_required_field(self) -> None:
        events = [
            _good_event(event_id=1),
            _good_event(event_id=2, primary_ticker=""),
            _good_event(event_id=3, primary_ticker="",
                        mechanism_family=""),
        ]
        result = _summarize(events)
        self.assertEqual(result["missing_fields"].get("primary_ticker"), 2)
        self.assertEqual(result["missing_fields"].get("mechanism_family"), 1)

    def test_no_missing_fields_when_all_complete(self) -> None:
        events = [_good_event(event_id=1), _good_event(event_id=2)]
        result = _summarize(events)
        # Either an empty dict or a dict whose every value is 0 — pin
        # the cleaner contract: no entry for a field that is never
        # missing.
        for k, v in result["missing_fields"].items():
            self.assertGreater(v, 0,
                               f"field {k!r} should not appear when count=0")


# ---------------------------------------------------------------------------
# Counts mirror validator
# ---------------------------------------------------------------------------


class TestValidationCounts(unittest.TestCase):
    def test_valid_invalid_counts_match_validator(self) -> None:
        events = [
            _good_event(event_id=1),
            _good_event(event_id=2, predicted_direction="bogus"),
            _good_event(event_id=3, primary_ticker=""),
        ]
        result = _summarize(events)
        self.assertEqual(result["total_events"], 3)
        self.assertEqual(result["valid_count"], 1)
        self.assertEqual(result["invalid_count"], 2)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_text_fields(self) -> None:
        result = _summarize([_good_event(predicted_direction="bogus")])
        all_text = " ".join(
            list(result.get("errors", []))
            + list(result.get("warnings", []))
        ).lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, all_text)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_nine_keys_in_json(self) -> None:
        out = StringIO()
        with _patch_loader([_good_event()]):
            rc = cli.main(["--yaml", "/x/curated.yaml", "--json"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(parsed["total_events"], 1)

    def test_cli_text_mode_runs(self) -> None:
        out = StringIO()
        with _patch_loader([_good_event()]):
            rc = cli.main(["--yaml", "/x/curated.yaml"], out=out)
        self.assertEqual(rc, 0)
        self.assertGreater(len(out.getvalue()), 0)


if __name__ == "__main__":
    unittest.main()
