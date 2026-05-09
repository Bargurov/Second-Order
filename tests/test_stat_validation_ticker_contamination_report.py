"""Tests for ``scripts/stat_validation_ticker_contamination_report.py``.

Pin the contract:

* The script reuses the readiness report's payload (via the patchable
  :func:`_run_readiness_report` seam) to identify fully-ready events,
  then reads ``headline`` and ``mechanism_family`` for those events
  via the patchable :func:`_load_event_metadata` seam.
* Four heuristic flags are surfaced per fully-ready event:
    - ``driv_lit_off_topic``      : primary in {DRIV, LIT} and headline
                                    has no auto/EV/lithium keyword
    - ``mechanism_family_none``   : mechanism_family null/empty/"none"
    - ``duplicate_date_ticker``   : (event_date, primary) repeats
    - ``local_off_topic_headline``: headline matches a local-news
                                    pattern (arrested, collision, etc)
* Aggregates count every fully-ready event the readiness payload
  surfaced.  ``--limit`` truncates ``examples`` only.
* Examples preserve id-ascending order, only include events with
  at least one flag, and never carry the un-flagged majority.
* Conservative language: recommended_next_action mentions
  "suspicious" or "manual review" but never "delete", "correct",
  "fix", or "auto" actions.
* The script does NOT assign new tickers — it only flags.
* No provider, yfinance, market_check, market_data, LLM, or FastAPI
  seam invoked.
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

from scripts import stat_validation_ticker_contamination_report as cli  # noqa: E402


_TOP_KEYS = (
    "ok",
    "total_fully_ready",
    "suspicious_count",
    "duplicate_date_ticker_count",
    "by_flag",
    "examples",
    "recommended_next_action",
)


_FLAG_KEYS = (
    "driv_lit_off_topic",
    "mechanism_family_none",
    "duplicate_date_ticker",
    "local_off_topic_headline",
)


_PER_EVENT_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "headline",
    "mechanism_family",
    "flags",
)


# ---------------------------------------------------------------------------
# Synthetic readiness payload + event-metadata helpers
# ---------------------------------------------------------------------------


def _make_fr_event(
    *,
    event_id: int,
    event_date: str | None = "2026-04-15",
    primary_ticker: str | None = "AAPL",
) -> dict:
    """Build one fully-ready readiness per-event entry.

    The contamination report only inspects fully-ready rows, so every
    readiness check is forced True here.  Tests that need a not-ready
    row to verify it is skipped should set ``fully_ready=False``
    directly via ``_make_not_ready_event``.
    """
    checks = {
        "has_event_date":               True,
        "has_market_tickers":           True,
        "forward_cache_1d":             True,
        "forward_cache_5d":             True,
        "forward_cache_20d":            True,
        "benchmark_proxy_available":    True,
        "estimation_window_sufficient": True,
    }
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
        "checks":         checks,
        "fully_ready":    True,
    }


def _make_not_ready_event(*, event_id: int) -> dict:
    return {
        "event_id":       event_id,
        "event_date":     "2026-04-15",
        "primary_ticker": "AAPL",
        "checks":         {
            "has_event_date":               False,
            "has_market_tickers":           True,
            "forward_cache_1d":             True,
            "forward_cache_5d":             True,
            "forward_cache_20d":            True,
            "benchmark_proxy_available":    True,
            "estimation_window_sufficient": True,
        },
        "fully_ready":    False,
    }


def _readiness_payload(events: list[dict]) -> dict:
    fully_ready_count = sum(1 for e in events if e["fully_ready"])
    return {
        "total_events":       len(events),
        "events_fully_ready": fully_ready_count,
        "events":             events,
        "recommended_next_action": "synthetic",
    }


def _patch_readiness(payload: dict):
    return patch.object(cli, "_run_readiness_report", return_value=payload)


def _patch_metadata(metadata: dict[int, dict]):
    return patch.object(cli, "_load_event_metadata", return_value=metadata)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        rc = cli.main(argv, out=out)
    except SystemExit as exc:
        rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(unittest.TestCase):
    def test_returns_dict_with_top_keys(self) -> None:
        payload = _readiness_payload([_make_fr_event(event_id=1)])
        with _patch_readiness(payload), _patch_metadata({}):
            result = cli.summarize_contamination()
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_by_flag_has_every_required_bucket(self) -> None:
        with _patch_readiness(_readiness_payload([])), _patch_metadata({}):
            result = cli.summarize_contamination()
        self.assertIsInstance(result["by_flag"], dict)
        for flag in _FLAG_KEYS:
            self.assertIn(flag, result["by_flag"],
                          f"missing flag bucket: {flag}")
            self.assertIsInstance(result["by_flag"][flag], int)

    def test_ok_is_true_on_clean_run(self) -> None:
        with _patch_readiness(_readiness_payload([])), _patch_metadata({}):
            result = cli.summarize_contamination()
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Empty / no-suspicious payloads
# ---------------------------------------------------------------------------


class TestEmptyAndClean(unittest.TestCase):
    def test_empty_archive_zeros_every_count(self) -> None:
        with _patch_readiness(_readiness_payload([])), _patch_metadata({}):
            result = cli.summarize_contamination()
        self.assertEqual(result["total_fully_ready"],          0)
        self.assertEqual(result["suspicious_count"],           0)
        self.assertEqual(result["duplicate_date_ticker_count"], 0)
        for flag in _FLAG_KEYS:
            self.assertEqual(result["by_flag"][flag], 0)
        self.assertEqual(result["examples"], [])
        self.assertIn("no fully-ready",
                      result["recommended_next_action"].lower())

    def test_only_not_ready_events_counts_zero_fully_ready(self) -> None:
        events = [_make_not_ready_event(event_id=1),
                  _make_not_ready_event(event_id=2)]
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata({}):
            result = cli.summarize_contamination()
        self.assertEqual(result["total_fully_ready"], 0)
        self.assertEqual(result["suspicious_count"],  0)
        self.assertEqual(result["examples"], [])

    def test_clean_fully_ready_event_yields_zero_suspicious(self) -> None:
        ev = _make_fr_event(event_id=10, primary_ticker="XOM",
                            event_date="2026-04-06")
        meta = {10: {"headline": "Saudis raise oil price as war riles markets",
                     "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["total_fully_ready"], 1)
        self.assertEqual(result["suspicious_count"],  0)
        for flag in _FLAG_KEYS:
            self.assertEqual(result["by_flag"][flag], 0)
        self.assertEqual(result["examples"], [])
        self.assertIn("no suspicious",
                      result["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# Flag: driv_lit_off_topic
# ---------------------------------------------------------------------------


class TestDrivLitOffTopicFlag(unittest.TestCase):
    def test_driv_with_off_topic_headline_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV",
                            event_date="2026-04-06")
        meta = {1: {"headline": "Murder arrest in Barnsley",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 1)
        self.assertEqual(result["suspicious_count"], 1)
        self.assertEqual(len(result["examples"]), 1)
        self.assertIn("driv_lit_off_topic", result["examples"][0]["flags"])

    def test_driv_with_auto_keyword_headline_is_not_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Tesla unveils new self-driving update",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 0)

    def test_lit_with_non_lithium_headline_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=2, primary_ticker="LIT")
        meta = {2: {"headline": "OPEC discusses output cuts",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 1)

    def test_lit_with_lithium_keyword_headline_is_not_flagged(self) -> None:
        ev = _make_fr_event(event_id=2, primary_ticker="LIT")
        meta = {2: {"headline": "Lithium prices surge on battery demand",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 0)

    def test_non_driv_lit_ticker_never_gets_this_flag(self) -> None:
        ev = _make_fr_event(event_id=3, primary_ticker="XOM")
        meta = {3: {"headline": "completely unrelated story",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 0)

    def test_driv_with_missing_headline_does_not_false_flag(self) -> None:
        # A None headline can't be judged off-topic — don't flag.
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": None, "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 0)


# ---------------------------------------------------------------------------
# Flag: mechanism_family_none
# ---------------------------------------------------------------------------


class TestMechanismFamilyNoneFlag(unittest.TestCase):
    def test_null_mechanism_family_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Saudi oil prices",
                    "mechanism_family": None}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 1)
        self.assertIn("mechanism_family_none",
                      result["examples"][0]["flags"])

    def test_empty_string_mechanism_family_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Saudi oil prices", "mechanism_family": ""}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 1)

    def test_string_none_mechanism_family_is_flagged(self) -> None:
        # The archive stores literal "none" for unclassified events
        # (see archive_stat_validation_run.by_mechanism_family output).
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Saudi oil prices", "mechanism_family": "none"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 1)

    def test_real_mechanism_family_is_not_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Saudi oil prices",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 0)


# ---------------------------------------------------------------------------
# Flag: duplicate_date_ticker
# ---------------------------------------------------------------------------


class TestDuplicateDateTickerFlag(unittest.TestCase):
    def test_two_events_same_date_same_ticker_both_flagged(self) -> None:
        events = [
            _make_fr_event(event_id=1, primary_ticker="XOM",
                           event_date="2026-04-06"),
            _make_fr_event(event_id=2, primary_ticker="XOM",
                           event_date="2026-04-06"),
        ]
        meta = {
            1: {"headline": "Saudi oil prices",
                "mechanism_family": "policy_constraint"},
            2: {"headline": "OPEC output cuts",
                "mechanism_family": "policy_constraint"},
        }
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 2)
        self.assertEqual(result["duplicate_date_ticker_count"], 2)
        flagged_ids = {e["event_id"] for e in result["examples"]
                       if "duplicate_date_ticker" in e["flags"]}
        self.assertEqual(flagged_ids, {1, 2})

    def test_three_events_same_date_same_ticker_all_three_flagged(self) -> None:
        events = [
            _make_fr_event(event_id=i, primary_ticker="DRIV",
                           event_date="2026-04-06")
            for i in (4, 6, 8)
        ]
        meta = {
            i: {"headline": "Tesla self-driving update",
                "mechanism_family": "policy_constraint"}
            for i in (4, 6, 8)
        }
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 3)
        self.assertEqual(result["duplicate_date_ticker_count"], 3)

    def test_different_dates_same_ticker_not_flagged(self) -> None:
        events = [
            _make_fr_event(event_id=1, primary_ticker="XOM",
                           event_date="2026-04-06"),
            _make_fr_event(event_id=2, primary_ticker="XOM",
                           event_date="2026-04-08"),
        ]
        meta = {
            1: {"headline": "Saudi oil",
                "mechanism_family": "policy_constraint"},
            2: {"headline": "OPEC cuts",
                "mechanism_family": "policy_constraint"},
        }
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 0)
        self.assertEqual(result["duplicate_date_ticker_count"], 0)

    def test_same_date_different_tickers_not_flagged(self) -> None:
        events = [
            _make_fr_event(event_id=1, primary_ticker="XOM",
                           event_date="2026-04-06"),
            _make_fr_event(event_id=2, primary_ticker="CVX",
                           event_date="2026-04-06"),
        ]
        meta = {
            1: {"headline": "Saudi oil",
                "mechanism_family": "policy_constraint"},
            2: {"headline": "OPEC cuts",
                "mechanism_family": "policy_constraint"},
        }
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 0)


# ---------------------------------------------------------------------------
# Flag: local_off_topic_headline
# ---------------------------------------------------------------------------


class TestLocalOffTopicHeadlineFlag(unittest.TestCase):
    def test_arrested_headline_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Two more arrested on suspicion of murder",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 1)
        self.assertIn("local_off_topic_headline",
                      result["examples"][0]["flags"])

    def test_pedestrian_collision_headline_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Pedestrian dies in Barnsley collision",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 1)

    def test_artemis_moon_headline_is_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Artemis II crew halfway to Moon",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 1)

    def test_legitimate_market_headline_is_not_flagged(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="XOM")
        meta = {1: {"headline": "Saudis Raise Oil Price to Record Premium",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 0)


# ---------------------------------------------------------------------------
# Multi-flag aggregation
# ---------------------------------------------------------------------------


class TestMultiFlagAggregation(unittest.TestCase):
    def test_event_can_carry_multiple_flags(self) -> None:
        events = [
            _make_fr_event(event_id=8, primary_ticker="DRIV",
                           event_date="2026-04-06"),
            _make_fr_event(event_id=9, primary_ticker="DRIV",
                           event_date="2026-04-06"),
        ]
        meta = {
            # ev 8 carries 4 flags: driv_lit_off_topic, mechanism_family_none,
            # duplicate_date_ticker, local_off_topic_headline.
            8: {"headline": "Two more arrested in Barnsley collision",
                "mechanism_family": "none"},
            # ev 9 carries 3 flags: driv_lit_off_topic (off-topic for DRIV),
            # mechanism_family_none, duplicate_date_ticker.  Headline is
            # picked to avoid the local-off-topic keyword list so the
            # asymmetry between events is visible.
            9: {"headline": "Quarterly earnings beat for unrelated firm",
                "mechanism_family": "none"},
        }
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"],     2)
        self.assertEqual(result["by_flag"]["mechanism_family_none"],  2)
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"],  2)
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 1)
        self.assertEqual(result["suspicious_count"], 2)
        ev8 = next(e for e in result["examples"] if e["event_id"] == 8)
        self.assertGreaterEqual(len(ev8["flags"]), 3)
        ev9 = next(e for e in result["examples"] if e["event_id"] == 9)
        self.assertNotIn("local_off_topic_headline", ev9["flags"])

    def test_suspicious_count_counts_events_not_flag_occurrences(self) -> None:
        # An event with 3 flags is still 1 suspicious event.
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Two arrested",
                    "mechanism_family": None}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(result["suspicious_count"], 1)
        # but flag occurrences may exceed 1
        total_flag_occurrences = sum(
            result["by_flag"][k] for k in _FLAG_KEYS
        )
        self.assertGreaterEqual(total_flag_occurrences, 2)


# ---------------------------------------------------------------------------
# Examples ordering, shape, and limit
# ---------------------------------------------------------------------------


class TestExamplesContract(unittest.TestCase):
    def test_examples_only_contain_suspicious_events(self) -> None:
        events = [
            _make_fr_event(event_id=1, primary_ticker="XOM"),
            _make_fr_event(event_id=2, primary_ticker="DRIV"),
        ]
        meta = {
            1: {"headline": "Saudi oil",
                "mechanism_family": "policy_constraint"},
            2: {"headline": "Random off topic story",
                "mechanism_family": "policy_constraint"},
        }
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        ids = {e["event_id"] for e in result["examples"]}
        self.assertNotIn(1, ids)
        self.assertIn(2, ids)

    def test_example_entry_has_expected_keys(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Two arrested",
                    "mechanism_family": None}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        self.assertEqual(len(result["examples"]), 1)
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, result["examples"][0])
        self.assertIsInstance(result["examples"][0]["flags"], list)

    def test_examples_sorted_by_event_id_ascending(self) -> None:
        events = [
            _make_fr_event(event_id=eid, primary_ticker="DRIV")
            for eid in (5, 2, 8, 1)
        ]
        meta = {eid: {"headline": "Random off-topic story",
                      "mechanism_family": "policy_constraint"}
                for eid in (5, 2, 8, 1)}
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        ids = [e["event_id"] for e in result["examples"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_examples_only(self) -> None:
        events = [
            _make_fr_event(event_id=eid, primary_ticker="DRIV")
            for eid in range(1, 11)
        ]
        meta = {eid: {"headline": "Random off-topic story",
                      "mechanism_family": "policy_constraint"}
                for eid in range(1, 11)}
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_contamination(limit=3)
        self.assertEqual(len(result["examples"]), 3)
        self.assertEqual(result["suspicious_count"], 10)
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 10)

    def test_negative_limit_clamps_to_zero(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Random off-topic story",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination(limit=-5)
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["suspicious_count"], 1)


# ---------------------------------------------------------------------------
# Conservative language
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    _BANNED = ("delete", "auto-correct", "auto correct", "auto-fix",
               "automatic", "fix the", "correct the")

    def test_recommended_action_uses_review_language_when_suspicious(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Random off-topic story",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_contamination()
        rec = result["recommended_next_action"].lower()
        self.assertTrue(
            "manual review" in rec or "suspicious" in rec
            or "needs review" in rec,
            f"recommended_next_action lacks review framing: {rec!r}",
        )

    def test_recommended_action_never_uses_destructive_or_auto_language(self) -> None:
        # Try every code path: empty, all-clean, suspicious.
        scenarios = [
            ([], {}),
            ([_make_fr_event(event_id=1, primary_ticker="XOM")],
             {1: {"headline": "Saudi oil",
                  "mechanism_family": "policy_constraint"}}),
            ([_make_fr_event(event_id=1, primary_ticker="DRIV")],
             {1: {"headline": "Random off-topic story",
                  "mechanism_family": "policy_constraint"}}),
        ]
        for evs, meta in scenarios:
            with _patch_readiness(_readiness_payload(evs)), \
                 _patch_metadata(meta):
                result = cli.summarize_contamination()
            rec = result["recommended_next_action"].lower()
            for banned in self._BANNED:
                self.assertNotIn(
                    banned, rec,
                    f"banned phrase {banned!r} appeared in: {rec!r}",
                )


# ---------------------------------------------------------------------------
# Pure helpers — keep them small + isolated.
# ---------------------------------------------------------------------------


class TestPureHelpers(unittest.TestCase):
    def test_is_driv_lit_off_topic_examples(self) -> None:
        # Off-topic
        self.assertTrue(cli._is_driv_lit_off_topic(
            "DRIV", "Murder in Barnsley"))
        self.assertTrue(cli._is_driv_lit_off_topic(
            "LIT",  "OPEC discusses output cuts"))
        # On-topic
        self.assertFalse(cli._is_driv_lit_off_topic(
            "DRIV", "Tesla self-driving update"))
        self.assertFalse(cli._is_driv_lit_off_topic(
            "LIT",  "Lithium prices surge on battery demand"))
        # Wrong ticker for this flag
        self.assertFalse(cli._is_driv_lit_off_topic(
            "XOM",  "Random story"))
        # Missing inputs
        self.assertFalse(cli._is_driv_lit_off_topic(None, "Random"))
        self.assertFalse(cli._is_driv_lit_off_topic("DRIV", None))
        self.assertFalse(cli._is_driv_lit_off_topic("DRIV", ""))

    def test_is_local_off_topic_headline_examples(self) -> None:
        self.assertTrue(cli._is_local_off_topic_headline(
            "Two arrested on suspicion of murder"))
        self.assertTrue(cli._is_local_off_topic_headline(
            "Pedestrian dies in collision"))
        self.assertTrue(cli._is_local_off_topic_headline(
            "Artemis II crew halfway to Moon"))
        # Legitimate
        self.assertFalse(cli._is_local_off_topic_headline(
            "Saudis raise oil price"))
        self.assertFalse(cli._is_local_off_topic_headline(
            "OPEC extends voluntary output cuts"))
        # Missing
        self.assertFalse(cli._is_local_off_topic_headline(None))
        self.assertFalse(cli._is_local_off_topic_headline(""))

    def test_is_mechanism_family_none_examples(self) -> None:
        self.assertTrue(cli._is_mechanism_family_none(None))
        self.assertTrue(cli._is_mechanism_family_none(""))
        self.assertTrue(cli._is_mechanism_family_none("none"))
        self.assertTrue(cli._is_mechanism_family_none("None"))
        self.assertTrue(cli._is_mechanism_family_none("  none  "))
        self.assertFalse(cli._is_mechanism_family_none("policy_constraint"))
        self.assertFalse(cli._is_mechanism_family_none("supply_shock"))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parseable_json(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Random off topic",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, parsed)

    def test_text_mode_includes_suspicious_count(self) -> None:
        ev = _make_fr_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Random off topic",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_readiness_payload([ev])), \
             _patch_metadata(meta):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("suspicious", output.lower())

    def test_limit_arg_caps_examples(self) -> None:
        events = [
            _make_fr_event(event_id=eid, primary_ticker="DRIV")
            for eid in range(1, 6)
        ]
        meta = {eid: {"headline": "Random off topic",
                      "mechanism_family": "policy_constraint"}
                for eid in range(1, 6)}
        with _patch_readiness(_readiness_payload(events)), \
             _patch_metadata(meta):
            rc, output = _run_cli(["--json", "--limit", "2"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(len(parsed["examples"]), 2)
        self.assertEqual(parsed["suspicious_count"], 5)


# ---------------------------------------------------------------------------
# End-to-end: real seams against a temp DB.
# ---------------------------------------------------------------------------


class TestEndToEndAgainstTempDb(unittest.TestCase):
    """Wire the un-patched seams against a synthetic SQLite DB to
    confirm the plumbing reaches the events table and the readiness
    report without provider/network/LLM calls.
    """

    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"contam_e2e_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE events ("
                " id INTEGER PRIMARY KEY,"
                " headline TEXT, event_date TEXT,"
                " market_tickers TEXT, mechanism_family TEXT)"
            )
            conn.execute(
                "CREATE TABLE price_cache ("
                " ticker TEXT, date TEXT, auto_adjust INTEGER)"
            )
            # No rows needed — readiness will return zero fully-ready.
            conn.commit()
        finally:
            conn.close()
        return path

    def test_runs_against_empty_temp_db_without_errors(self) -> None:
        path = self._make_temp_db()
        try:
            result = cli.summarize_contamination(db_path=path)
        finally:
            os.unlink(path)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["total_fully_ready"], 0)
        self.assertEqual(result["suspicious_count"],  0)

    def test_load_event_metadata_returns_expected_shape(self) -> None:
        path = self._make_temp_db()
        try:
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "INSERT INTO events (id, headline, event_date,"
                    " market_tickers, mechanism_family) VALUES"
                    " (1, 'Saudi oil headline', '2026-04-06',"
                    "  '[{\"symbol\":\"XOM\"}]', 'policy_constraint')"
                )
                conn.commit()
            finally:
                conn.close()
            md = cli._load_event_metadata(db_path=path, event_ids=[1, 99])
        finally:
            os.unlink(path)
        self.assertIn(1, md)
        self.assertEqual(md[1]["headline"], "Saudi oil headline")
        self.assertEqual(md[1]["mechanism_family"], "policy_constraint")
        # missing id should not raise; just absent or have empty values
        if 99 in md:
            self.assertIsNone(md[99].get("headline"))


if __name__ == "__main__":
    unittest.main()
