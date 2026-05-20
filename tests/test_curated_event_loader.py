"""Tests for ``scripts/curated_event_loader.py``.

Pin the contract:

* ``load_curated_events(yaml_path)`` returns ``list[dict]`` regardless
  of whether the YAML file's top level is a list or a mapping with an
  ``events:`` key.
* Missing path → empty list (the validator surfaces "no events" as
  its own concern; the loader doesn't raise on missing files).
* Malformed YAML → empty list + a parse error written through the
  ``errors`` out-parameter (the loader is tolerant; the validator
  decides how to react).
* Each event entry is a plain dict with verbatim keys / values from
  the YAML (no field renaming or coercion at this layer).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import curated_event_loader as cli  # noqa: E402


def _write_yaml(text: str, *, suffix: str = "yaml") -> str:
    path = os.path.join(
        tempfile.gettempdir(), f"curated_{uuid.uuid4().hex}.{suffix}",
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# YAML shapes
# ---------------------------------------------------------------------------


class TestYamlShapes(unittest.TestCase):
    def test_top_level_list_returns_list_of_dicts(self) -> None:
        path = _write_yaml(
            "- event_id: 1\n"
            "  event_date: 2026-04-01\n"
            "  headline: First\n"
            "- event_id: 2\n"
            "  event_date: 2026-04-02\n"
            "  headline: Second\n"
        )
        try:
            events, errors = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        self.assertEqual(errors, [])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_id"], 1)
        self.assertEqual(events[1]["headline"], "Second")

    def test_top_level_mapping_with_events_key(self) -> None:
        path = _write_yaml(
            "events:\n"
            "  - event_id: 1\n"
            "    headline: First\n"
        )
        try:
            events, errors = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        self.assertEqual(errors, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], 1)

    def test_top_level_mapping_without_events_key_is_empty(self) -> None:
        # A mapping with no `events:` field returns an empty list and
        # surfaces a structural error so the validator can flag it.
        path = _write_yaml("not_events:\n  - event_id: 1\n")
        try:
            events, errors = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        self.assertEqual(events, [])
        self.assertTrue(errors,
                        "expected a structural error for missing 'events:'")


# ---------------------------------------------------------------------------
# Tolerance for missing / malformed input
# ---------------------------------------------------------------------------


class TestTolerantLoading(unittest.TestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        events, errors = cli.load_curated_events("/no/such/file.yaml")
        self.assertEqual(events, [])
        self.assertTrue(errors,
                        "expected a missing-file error in errors list")

    def test_malformed_yaml_returns_empty_list_and_error(self) -> None:
        path = _write_yaml("not: valid: yaml: : :\n")
        try:
            events, errors = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        self.assertEqual(events, [])
        self.assertTrue(errors)

    def test_empty_yaml_returns_empty_list(self) -> None:
        path = _write_yaml("")
        try:
            events, errors = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        self.assertEqual(events, [])
        # An empty file is not a parse error — just no events to load.
        self.assertEqual(errors, [])

    def test_none_path_returns_empty_list(self) -> None:
        events, errors = cli.load_curated_events(None)
        self.assertEqual(events, [])
        self.assertTrue(errors)


# ---------------------------------------------------------------------------
# Field passthrough
# ---------------------------------------------------------------------------


class TestFieldPassthrough(unittest.TestCase):
    def test_all_eleven_fields_round_trip(self) -> None:
        path = _write_yaml(
            "- event_id: 1\n"
            "  event_date: 2026-04-01\n"
            "  headline: Headline\n"
            "  source_url: https://example.com/article\n"
            "  primary_ticker: MS\n"
            "  benchmark_ticker: SPY\n"
            "  mechanism_family: bank_regulatory_capital_relief\n"
            "  mechanism_description: A bank-relief description.\n"
            "  predicted_direction: up\n"
            "  prediction_rationale: Capital relief lifts dividend capacity.\n"
            "  curator_notes: Loaded from analyst review.\n"
        )
        try:
            events, errors = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        self.assertEqual(errors, [])
        self.assertEqual(len(events), 1)
        e = events[0]
        for field in (
            "event_id", "event_date", "headline", "source_url",
            "primary_ticker", "benchmark_ticker", "mechanism_family",
            "mechanism_description", "predicted_direction",
            "prediction_rationale", "curator_notes",
        ):
            self.assertIn(field, e, f"missing {field}")

    def test_iso_event_date_returned_as_date_or_string(self) -> None:
        # PyYAML coerces `2026-04-01` to a date object by default.  The
        # loader must NOT silently coerce it to a string at this layer
        # — keeping the value verbatim lets the validator handle date
        # parsing for both date objects and strings.
        path = _write_yaml(
            "- event_id: 1\n"
            "  event_date: 2026-04-01\n"
        )
        try:
            events, _ = cli.load_curated_events(path)
        finally:
            os.unlink(path)
        # Either type is acceptable as long as the validator can
        # interpret it; we only pin that *something* is there.
        self.assertIsNotNone(events[0]["event_date"])


if __name__ == "__main__":
    unittest.main()
