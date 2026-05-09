"""Tests for ``scripts/stat_validation_short_horizon_contamination_report.py``.

Pin the contract:

* The script reuses the short-horizon readiness report's payload (via
  the patchable :func:`_run_short_horizon_readiness_report` seam) to
  identify short-horizon-ready events, then reads ``headline`` and
  ``mechanism_family`` for those events via the patchable
  :func:`_load_event_metadata` seam (re-exported from the fully-ready
  contamination report so its tests are not perturbed).
* Four heuristic flags surface per short-horizon-ready event:
    - ``driv_lit_off_topic``      : primary in {DRIV, LIT} and
                                    headline has no auto/EV/lithium kw
    - ``mechanism_family_none``   : mechanism_family null/empty/"none"
    - ``duplicate_date_ticker``   : (event_date, primary) repeats
    - ``local_off_topic_headline``: headline matches a local-news
                                    pattern (arrested, collision, ...)
* Aggregates count every short-horizon-ready event the readiness
  payload surfaced.  ``--limit`` truncates ``examples`` only.
* Examples preserve id-ascending order, only include events with
  at least one flag, and never carry the un-flagged majority.
* Conservative language: recommended_next_action mentions
  "suspicious" or "manual review" but never "delete", "correct",
  "fix", or "auto" actions.
* ``clean_short_ready_count`` = ``total_short_ready - suspicious_count``.
* The script does NOT assign new tickers — it only flags.
* No provider, yfinance, market_check, market_data, LLM, or FastAPI
  seam invoked.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import (  # noqa: E402
    stat_validation_short_horizon_contamination_report as cli,
)


_TOP_KEYS = (
    "ok",
    "total_short_ready",
    "suspicious_count",
    "clean_short_ready_count",
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
# Synthetic short-horizon readiness payload + event-metadata helpers
# ---------------------------------------------------------------------------


def _make_short_ready_event(
    *,
    event_id: int,
    event_date: str | None = "2026-04-15",
    primary_ticker: str | None = "AAPL",
) -> dict:
    """Build one short-horizon-ready readiness per-event entry.

    The contamination report only inspects ``ready_1d5d`` rows, so
    every readiness check is forced True here.  Tests that need a
    not-ready row to verify it is skipped should use
    ``_make_not_ready_event``.
    """
    checks = {
        "has_event_date":               True,
        "has_market_tickers":           True,
        "forward_cache_1d":             True,
        "forward_cache_5d":             True,
        "benchmark_proxy_available_5d": True,
        "estimation_window_sufficient": True,
    }
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
        "checks":         checks,
        "ready_1d5d":     True,
        "delta_eligible": False,
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
            "benchmark_proxy_available_5d": True,
            "estimation_window_sufficient": True,
        },
        "ready_1d5d":     False,
        "delta_eligible": False,
    }


def _short_readiness_payload(events: list[dict]) -> dict:
    n_ready = sum(1 for e in events if e.get("ready_1d5d"))
    return {
        "total_events":                          len(events),
        "events_ready_1d5d":                     n_ready,
        "delta_vs_full_ready":                   0,
        "missing_tickers_count":                 0,
        "missing_benchmark_count":               0,
        "insufficient_estimation_window_count":  0,
        "examples":                              events,
        "recommended_next_action":               "synthetic",
    }


def _patch_readiness(payload: dict):
    return patch.object(
        cli, "_run_short_horizon_readiness_report", return_value=payload,
    )


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
        payload = _short_readiness_payload([_make_short_ready_event(event_id=1)])
        with _patch_readiness(payload), _patch_metadata({}):
            result = cli.summarize_short_horizon_contamination()
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_by_flag_has_every_required_bucket(self) -> None:
        with _patch_readiness(_short_readiness_payload([])), \
             _patch_metadata({}):
            result = cli.summarize_short_horizon_contamination()
        self.assertIsInstance(result["by_flag"], dict)
        for flag in _FLAG_KEYS:
            self.assertIn(flag, result["by_flag"],
                          f"missing flag bucket: {flag}")
            self.assertIsInstance(result["by_flag"][flag], int)

    def test_ok_is_true_on_clean_run(self) -> None:
        with _patch_readiness(_short_readiness_payload([])), \
             _patch_metadata({}):
            result = cli.summarize_short_horizon_contamination()
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Empty / no-suspicious payloads
# ---------------------------------------------------------------------------


class TestEmptyAndClean(unittest.TestCase):
    def test_empty_archive_zeros_every_count(self) -> None:
        with _patch_readiness(_short_readiness_payload([])), \
             _patch_metadata({}):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["total_short_ready"],       0)
        self.assertEqual(result["suspicious_count"],        0)
        self.assertEqual(result["clean_short_ready_count"], 0)
        for flag in _FLAG_KEYS:
            self.assertEqual(result["by_flag"][flag], 0)
        self.assertEqual(result["examples"], [])
        self.assertIn(
            "no short-horizon",
            result["recommended_next_action"].lower(),
        )

    def test_only_not_ready_events_counts_zero_short_ready(self) -> None:
        events = [_make_not_ready_event(event_id=1),
                  _make_not_ready_event(event_id=2)]
        with _patch_readiness(_short_readiness_payload(events)), \
             _patch_metadata({}):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["total_short_ready"],       0)
        self.assertEqual(result["suspicious_count"],        0)
        self.assertEqual(result["clean_short_ready_count"], 0)
        self.assertEqual(result["examples"], [])

    def test_clean_short_ready_event_yields_zero_suspicious(self) -> None:
        ev = _make_short_ready_event(event_id=10, primary_ticker="XOM",
                                     event_date="2026-04-06")
        meta = {10: {"headline": "Saudis raise oil price as war riles markets",
                     "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["total_short_ready"],       1)
        self.assertEqual(result["suspicious_count"],        0)
        self.assertEqual(result["clean_short_ready_count"], 1)
        for flag in _FLAG_KEYS:
            self.assertEqual(result["by_flag"][flag], 0)
        self.assertEqual(result["examples"], [])
        self.assertIn(
            "no suspicious",
            result["recommended_next_action"].lower(),
        )


# ---------------------------------------------------------------------------
# Flag: driv_lit_off_topic
# ---------------------------------------------------------------------------


class TestDrivLitOffTopicFlag(unittest.TestCase):
    def test_driv_with_off_topic_headline_is_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="DRIV",
                                     event_date="2026-04-06")
        meta = {1: {"headline": "Murder arrest in Barnsley",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 1)
        self.assertEqual(result["suspicious_count"], 1)
        self.assertEqual(len(result["examples"]), 1)
        self.assertIn("driv_lit_off_topic", result["examples"][0]["flags"])

    def test_driv_with_auto_keyword_headline_is_not_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Tesla unveils new self-driving update",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 0)

    def test_lit_with_non_lithium_headline_is_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=2, primary_ticker="LIT")
        meta = {2: {"headline": "OPEC discusses output cuts",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["driv_lit_off_topic"], 1)


# ---------------------------------------------------------------------------
# Flag: mechanism_family_none
# ---------------------------------------------------------------------------


class TestMechanismFamilyNoneFlag(unittest.TestCase):
    def test_null_family_is_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple launches new product",
                    "mechanism_family": None}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 1)

    def test_literal_none_string_is_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple launches new product",
                    "mechanism_family": "none"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 1)

    def test_empty_string_is_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple launches new product",
                    "mechanism_family": "  "}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 1)

    def test_real_family_is_not_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple launches new product",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["mechanism_family_none"], 0)


# ---------------------------------------------------------------------------
# Flag: duplicate_date_ticker
# ---------------------------------------------------------------------------


class TestDuplicateDateTickerFlag(unittest.TestCase):
    def test_two_events_share_pair_both_flagged(self) -> None:
        ev1 = _make_short_ready_event(event_id=1, primary_ticker="JPM",
                                      event_date="2026-04-06")
        ev2 = _make_short_ready_event(event_id=2, primary_ticker="JPM",
                                      event_date="2026-04-06")
        meta = {
            1: {"headline": "JPM earnings",
                "mechanism_family": "earnings_signal"},
            2: {"headline": "JPM dividend hike",
                "mechanism_family": "earnings_signal"},
        }
        with _patch_readiness(_short_readiness_payload([ev1, ev2])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 2)
        self.assertEqual(result["suspicious_count"], 2)

    def test_distinct_pairs_are_not_flagged(self) -> None:
        ev1 = _make_short_ready_event(event_id=1, primary_ticker="JPM",
                                      event_date="2026-04-06")
        ev2 = _make_short_ready_event(event_id=2, primary_ticker="GS",
                                      event_date="2026-04-06")
        meta = {
            1: {"headline": "JPM earnings",
                "mechanism_family": "earnings_signal"},
            2: {"headline": "GS earnings",
                "mechanism_family": "earnings_signal"},
        }
        with _patch_readiness(_short_readiness_payload([ev1, ev2])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 0)

    def test_ticker_case_normalized(self) -> None:
        # 'jpm' / 'JPM' should collide as the same pair.
        ev1 = _make_short_ready_event(event_id=1, primary_ticker="jpm",
                                      event_date="2026-04-06")
        ev2 = _make_short_ready_event(event_id=2, primary_ticker="JPM",
                                      event_date="2026-04-06")
        meta = {
            1: {"headline": "JPM earnings",
                "mechanism_family": "earnings_signal"},
            2: {"headline": "JPM dividend",
                "mechanism_family": "earnings_signal"},
        }
        with _patch_readiness(_short_readiness_payload([ev1, ev2])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["duplicate_date_ticker"], 2)


# ---------------------------------------------------------------------------
# Flag: local_off_topic_headline
# ---------------------------------------------------------------------------


class TestLocalOffTopicHeadlineFlag(unittest.TestCase):
    def test_local_news_keyword_is_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Pedestrian killed in collision on Main St",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 1)

    def test_real_market_headline_is_not_flagged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple announces $100B buyback",
                    "mechanism_family": "policy_constraint"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["by_flag"]["local_off_topic_headline"], 0)


# ---------------------------------------------------------------------------
# Multi-flag stacking on a single event
# ---------------------------------------------------------------------------


class TestStackedFlags(unittest.TestCase):
    def test_event_can_carry_multiple_flags(self) -> None:
        # DRIV with off-topic local-news headline and null family,
        # AND duplicated against a sibling: all four flags fire.
        ev1 = _make_short_ready_event(event_id=1, primary_ticker="DRIV",
                                      event_date="2026-04-06")
        ev2 = _make_short_ready_event(event_id=2, primary_ticker="DRIV",
                                      event_date="2026-04-06")
        meta = {
            1: {"headline": "Pedestrian arrested in Barnsley collision",
                "mechanism_family": None},
            2: {"headline": "Tesla autonomous update",
                "mechanism_family": "policy_constraint"},
        }
        with _patch_readiness(_short_readiness_payload([ev1, ev2])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        # Event 1 gets all four flags; event 2 only gets duplicate.
        ev1_entry = next(e for e in result["examples"] if e["event_id"] == 1)
        self.assertEqual(
            sorted(ev1_entry["flags"]),
            sorted([
                "driv_lit_off_topic",
                "mechanism_family_none",
                "duplicate_date_ticker",
                "local_off_topic_headline",
            ]),
        )
        self.assertEqual(result["suspicious_count"], 2)


# ---------------------------------------------------------------------------
# Aggregates + clean count derivation
# ---------------------------------------------------------------------------


class TestAggregates(unittest.TestCase):
    def test_clean_count_equals_total_minus_suspicious(self) -> None:
        ev_clean1 = _make_short_ready_event(event_id=1, primary_ticker="AAPL",
                                            event_date="2026-04-06")
        ev_clean2 = _make_short_ready_event(event_id=2, primary_ticker="MSFT",
                                            event_date="2026-04-07")
        ev_dirty  = _make_short_ready_event(event_id=3, primary_ticker="DRIV",
                                            event_date="2026-04-08")
        meta = {
            1: {"headline": "Apple earnings beat", "mechanism_family": "earnings_signal"},
            2: {"headline": "Microsoft Azure growth", "mechanism_family": "earnings_signal"},
            3: {"headline": "Murder arrest",       "mechanism_family": None},
        }
        with _patch_readiness(_short_readiness_payload(
                [ev_clean1, ev_clean2, ev_dirty])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["total_short_ready"], 3)
        self.assertEqual(result["suspicious_count"], 1)
        self.assertEqual(result["clean_short_ready_count"], 2)

    def test_aggregates_count_every_short_ready_not_just_examples(
        self,
    ) -> None:
        # 30 dirty events; --limit 5 truncates examples but counts
        # remain accurate.
        events = [
            _make_short_ready_event(event_id=i, primary_ticker="DRIV",
                                    event_date="2026-04-06")
            for i in range(1, 31)
        ]
        meta = {
            i: {"headline": "Murder arrest", "mechanism_family": None}
            for i in range(1, 31)
        }
        with _patch_readiness(_short_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination(limit=5)
        self.assertEqual(result["total_short_ready"], 30)
        self.assertEqual(result["suspicious_count"], 30)
        self.assertEqual(result["clean_short_ready_count"], 0)
        self.assertEqual(len(result["examples"]), 5)


# ---------------------------------------------------------------------------
# Examples ordering + filter
# ---------------------------------------------------------------------------


class TestExamplesOrderingAndFilter(unittest.TestCase):
    def test_examples_only_include_suspicious(self) -> None:
        ev_clean = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        ev_dirty = _make_short_ready_event(event_id=2, primary_ticker="DRIV")
        meta = {
            1: {"headline": "Apple earnings", "mechanism_family": "earnings_signal"},
            2: {"headline": "Murder arrest",  "mechanism_family": None},
        }
        with _patch_readiness(_short_readiness_payload([ev_clean, ev_dirty])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        ids = [e["event_id"] for e in result["examples"]]
        self.assertEqual(ids, [2])

    def test_examples_id_ascending(self) -> None:
        events = [
            _make_short_ready_event(event_id=i, primary_ticker="DRIV",
                                    event_date=f"2026-04-{i:02d}")
            for i in (3, 1, 2)
        ]
        meta = {
            i: {"headline": "Murder arrest", "mechanism_family": None}
            for i in (1, 2, 3)
        }
        with _patch_readiness(_short_readiness_payload(events)), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        ids = [e["event_id"] for e in result["examples"]]
        self.assertEqual(ids, sorted(ids))

    def test_each_example_has_required_keys(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Murder arrest", "mechanism_family": None}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(len(result["examples"]), 1)
        for k in _PER_EVENT_KEYS:
            self.assertIn(k, result["examples"][0])


# ---------------------------------------------------------------------------
# Recommendation language
# ---------------------------------------------------------------------------


class TestRecommendationLanguage(unittest.TestCase):
    _FORBIDDEN = ("delete", "auto-correct", "auto-fix", "rewrite",
                  "auto-assign")

    def test_no_destructive_language_in_any_branch(self) -> None:
        for events in (
            [],
            [_make_short_ready_event(event_id=1, primary_ticker="AAPL")],
            [_make_short_ready_event(event_id=1, primary_ticker="DRIV")],
        ):
            meta = {1: {"headline": "Apple earnings",
                        "mechanism_family": "earnings_signal"}}
            with _patch_readiness(_short_readiness_payload(events)), \
                 _patch_metadata(meta):
                result = cli.summarize_short_horizon_contamination()
            text = result["recommended_next_action"].lower()
            for bad in self._FORBIDDEN:
                self.assertNotIn(bad, text,
                                 f"forbidden phrase {bad!r} in: {text}")

    def test_gaps_branch_mentions_manual_review(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Murder arrest", "mechanism_family": None}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertIn("manual review", result["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# Limit behavior
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_negative_limit_clamps_to_zero(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Murder arrest", "mechanism_family": None}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination(limit=-3)
        self.assertEqual(result["examples"], [])
        # Aggregate counts unaffected by limit clamping.
        self.assertEqual(result["suspicious_count"], 1)
        self.assertEqual(result["total_short_ready"], 1)


# ---------------------------------------------------------------------------
# Seam isolation — never assigns tickers, no provider/yfinance, etc.
# ---------------------------------------------------------------------------


class TestSeamIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_no_provider_or_fastapi_imports_on_default_run(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED)}
        with _patch_readiness(_short_readiness_payload([])), \
             _patch_metadata({}):
            cli.summarize_short_horizon_contamination()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED)}
        self.assertEqual(after - before, set())

    def test_seam_for_short_horizon_readiness_exists(self) -> None:
        self.assertTrue(callable(getattr(
            cli, "_run_short_horizon_readiness_report")))

    def test_seam_for_metadata_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_load_event_metadata")))


# ---------------------------------------------------------------------------
# Per-event entries reflect the metadata fields, not invented ones
# ---------------------------------------------------------------------------


class TestNoTickerAssignment(unittest.TestCase):
    def test_examples_carry_input_ticker_unchanged(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="DRIV")
        meta = {1: {"headline": "Murder arrest", "mechanism_family": None}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            result = cli.summarize_short_horizon_contamination()
        self.assertEqual(result["examples"][0]["primary_ticker"], "DRIV")
        # No "proposed_ticker" / "replacement" / similar field; the
        # report flags but never assigns.
        for entry in result["examples"]:
            for k in entry.keys():
                self.assertNotIn(
                    "propose", k.lower(),
                    f"unexpected proposal-style key: {k}",
                )
                self.assertNotIn(
                    "replace", k.lower(),
                    f"unexpected replacement-style key: {k}",
                )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parseable_payload(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple earnings",
                    "mechanism_family": "earnings_signal"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _TOP_KEYS:
            self.assertIn(k, parsed)

    def test_default_text_run_does_not_crash(self) -> None:
        ev = _make_short_ready_event(event_id=1, primary_ticker="AAPL")
        meta = {1: {"headline": "Apple earnings",
                    "mechanism_family": "earnings_signal"}}
        with _patch_readiness(_short_readiness_payload([ev])), \
             _patch_metadata(meta):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("Short-horizon", output)

    def test_limit_flag_truncates_examples(self) -> None:
        events = [
            _make_short_ready_event(event_id=i, primary_ticker="DRIV",
                                    event_date=f"2026-04-{i:02d}")
            for i in range(1, 6)
        ]
        meta = {
            i: {"headline": "Murder arrest", "mechanism_family": None}
            for i in range(1, 6)
        }
        with _patch_readiness(_short_readiness_payload(events)), \
             _patch_metadata(meta):
            rc, output = _run_cli(["--json", "--limit", "2"])
        parsed = json.loads(output)
        self.assertEqual(parsed["suspicious_count"], 5)
        self.assertEqual(len(parsed["examples"]), 2)


if __name__ == "__main__":
    unittest.main()
