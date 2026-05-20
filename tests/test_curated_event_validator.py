"""Tests for ``scripts/curated_event_validator.py``.

Pin the contract:

* ``validate_curated_events(events)`` returns a dict with::

    {
      "ok":               bool,    # True iff every event validates
      "valid_count":      int,
      "invalid_count":    int,
      "validated_events": [dict, ...],   # parse-coerced copy of input
      "errors_by_event_id": {str(event_id): [str, ...], ...},
      "errors":           [str, ...],    # structural errors not tied
                                          # to a specific event_id
    }

* Required fields (every event must have non-blank values):
    event_id, event_date, headline, source_url, primary_ticker,
    benchmark_ticker, mechanism_family, mechanism_description,
    predicted_direction, prediction_rationale.
* Optional: curator_notes.
* event_date must parse as ISO-8601 (YYYY-MM-DD).  Both string and
  ``datetime.date`` inputs are accepted; anything else fails.
* primary_ticker / benchmark_ticker / mechanism_family must be
  non-blank strings.
* predicted_direction must be one of {"up", "down", "flat"}.
* The CLI ``main`` returns 0 on success, non-zero when any event
  fails validation.
* Conservative wording: error strings never claim "proof" / "alpha"
  / "automatic"; they describe the missing or invalid field only.
"""
from __future__ import annotations

import datetime as _dt
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

from scripts import curated_event_validator as cli  # noqa: E402


_BANNED_WORDS = (
    "proof",
    "alpha",
    "automatic",
)


def _good_event(**overrides) -> dict:
    base = {
        "event_id":              1,
        "event_date":            _dt.date(2026, 4, 1),
        "headline":              "Bank announces dividend increase",
        "source_url":            "https://example.com/article",
        "primary_ticker":        "MS",
        "benchmark_ticker":      "SPY",
        "mechanism_family":      "bank_regulatory_capital_relief",
        "mechanism_description": "Capital relief enables higher payouts.",
        "predicted_direction":   "up",
        "prediction_rationale":  "Section 23A exemption lifts capital ratio.",
        "curator_notes":         "Curator hand-reviewed the FRB release.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_valid_event_validates(self) -> None:
        result = cli.validate_curated_events([_good_event()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["valid_count"], 1)
        self.assertEqual(result["invalid_count"], 0)
        self.assertEqual(result["errors_by_event_id"], {})

    def test_empty_list_is_not_ok(self) -> None:
        # An empty curated archive isn't valid — validator surfaces
        # this as a structural error.
        result = cli.validate_curated_events([])
        self.assertFalse(result["ok"])
        self.assertEqual(result["valid_count"], 0)

    def test_validated_events_carries_input_back(self) -> None:
        event = _good_event(event_id=42)
        result = cli.validate_curated_events([event])
        self.assertEqual(len(result["validated_events"]), 1)
        self.assertEqual(result["validated_events"][0]["event_id"], 42)


# ---------------------------------------------------------------------------
# Required field checks
# ---------------------------------------------------------------------------


class TestRequiredFields(unittest.TestCase):
    REQUIRED = (
        "event_id", "event_date", "headline", "source_url",
        "primary_ticker", "benchmark_ticker", "mechanism_family",
        "mechanism_description", "predicted_direction",
        "prediction_rationale",
    )

    def test_each_required_field_when_missing_invalidates(self) -> None:
        for field in self.REQUIRED:
            event = _good_event()
            del event[field]
            result = cli.validate_curated_events([event])
            self.assertFalse(
                result["ok"],
                f"event missing {field!r} should fail validation",
            )
            self.assertEqual(result["invalid_count"], 1)
            errs = result["errors_by_event_id"].get(str(event.get("event_id")))
            if errs is None and field == "event_id":
                # Missing event_id falls into the structural-errors
                # bucket since there's no id to key on.
                self.assertTrue(result["errors"],
                                "missing event_id needs a structural error")
            else:
                self.assertTrue(errs)

    def test_curator_notes_is_optional(self) -> None:
        event = _good_event()
        del event["curator_notes"]
        result = cli.validate_curated_events([event])
        self.assertTrue(result["ok"], f"errors: {result.get('errors')}")


# ---------------------------------------------------------------------------
# Specific value checks
# ---------------------------------------------------------------------------


class TestEventDateParsing(unittest.TestCase):
    def test_iso_string_event_date_validates(self) -> None:
        result = cli.validate_curated_events([
            _good_event(event_date="2026-04-01"),
        ])
        self.assertTrue(result["ok"])

    def test_invalid_date_string_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(event_date="2026-13-99"),
        ])
        self.assertFalse(result["ok"])
        errs = result["errors_by_event_id"]["1"]
        self.assertTrue(any("event_date" in e.lower() for e in errs))

    def test_non_iso_format_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(event_date="04/01/2026"),
        ])
        self.assertFalse(result["ok"])

    def test_python_date_object_validates(self) -> None:
        result = cli.validate_curated_events([
            _good_event(event_date=_dt.date(2026, 4, 1)),
        ])
        self.assertTrue(result["ok"])


class TestBlankTickerChecks(unittest.TestCase):
    def test_blank_primary_ticker_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(primary_ticker=""),
        ])
        self.assertFalse(result["ok"])
        errs = result["errors_by_event_id"]["1"]
        self.assertTrue(any("primary_ticker" in e for e in errs))

    def test_whitespace_primary_ticker_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(primary_ticker="   "),
        ])
        self.assertFalse(result["ok"])

    def test_blank_benchmark_ticker_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(benchmark_ticker=""),
        ])
        self.assertFalse(result["ok"])
        errs = result["errors_by_event_id"]["1"]
        self.assertTrue(any("benchmark_ticker" in e for e in errs))


class TestMechanismFamilyCheck(unittest.TestCase):
    def test_blank_mechanism_family_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(mechanism_family=""),
        ])
        self.assertFalse(result["ok"])
        errs = result["errors_by_event_id"]["1"]
        self.assertTrue(any("mechanism_family" in e for e in errs))


class TestPredictedDirectionCheck(unittest.TestCase):
    def test_up_validates(self) -> None:
        result = cli.validate_curated_events([
            _good_event(predicted_direction="up"),
        ])
        self.assertTrue(result["ok"])

    def test_down_validates(self) -> None:
        result = cli.validate_curated_events([
            _good_event(predicted_direction="down"),
        ])
        self.assertTrue(result["ok"])

    def test_flat_validates(self) -> None:
        result = cli.validate_curated_events([
            _good_event(predicted_direction="flat"),
        ])
        self.assertTrue(result["ok"])

    def test_invalid_direction_string_fails(self) -> None:
        result = cli.validate_curated_events([
            _good_event(predicted_direction="bullish"),
        ])
        self.assertFalse(result["ok"])
        errs = result["errors_by_event_id"]["1"]
        self.assertTrue(any("predicted_direction" in e for e in errs))


# ---------------------------------------------------------------------------
# Multi-event aggregation
# ---------------------------------------------------------------------------


class TestMultiEventAggregation(unittest.TestCase):
    def test_mixed_validity_keeps_only_valid_events_in_validated(self) -> None:
        events = [
            _good_event(event_id=1),
            _good_event(event_id=2, predicted_direction="bogus"),
            _good_event(event_id=3),
        ]
        result = cli.validate_curated_events(events)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["invalid_count"], 1)
        valid_ids = {e["event_id"] for e in result["validated_events"]}
        self.assertEqual(valid_ids, {1, 3})


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_error_text(self) -> None:
        events = [_good_event(event_date="bad", primary_ticker="")]
        result = cli.validate_curated_events(events)
        all_text = " ".join(
            sum((errs for errs in result["errors_by_event_id"].values()),
                start=list(result["errors"]))
        ).lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, all_text,
                             f"banned word {w!r} in: {all_text!r}")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _patch_loader(events: list[dict], errors: list[str] | None = None):
    return patch.object(
        cli, "_load_curated_events",
        return_value=(list(events), list(errors or [])),
    )


class TestCLI(unittest.TestCase):
    def test_cli_returns_zero_on_valid_yaml(self) -> None:
        out = StringIO()
        with _patch_loader([_good_event()]):
            rc = cli.main(["--yaml", "/x/curated.yaml", "--json"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertTrue(parsed["ok"])

    def test_cli_returns_nonzero_on_invalid_yaml(self) -> None:
        out = StringIO()
        with _patch_loader([_good_event(predicted_direction="bogus")]):
            rc = cli.main(["--yaml", "/x/curated.yaml", "--json"], out=out)
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertFalse(parsed["ok"])

    def test_cli_text_mode_runs(self) -> None:
        out = StringIO()
        with _patch_loader([_good_event()]):
            rc = cli.main(["--yaml", "/x/curated.yaml"], out=out)
        self.assertEqual(rc, 0)
        self.assertIn("ok", out.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
