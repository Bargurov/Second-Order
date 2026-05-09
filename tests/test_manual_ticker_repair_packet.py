"""Tests for ``scripts/manual_ticker_repair_packet.py``.

Pin the contract:

* The packet builds on :func:`scripts.manual_ticker_repair_shortlist
  .summarize_repair_shortlist` through the patchable seam
  ``_run_repair_shortlist`` so unit tests can drive it with
  synthetic shortlist payloads.
* A second SELECT-only patchable seam ``_fetch_event_dates`` enriches
  each candidate with the event's ``event_date`` (the shortlist does
  not surface this column).  Both seams are patchable so unit tests
  never hit a real DB.
* Default ``--priority`` filter is ``medium`` — the medium bucket is
  the deepest pool of recoverable rows, ranked by an estimated
  ``fast_to_clean_score`` so operators inspect the highest-leverage
  rows first.  ``--priority all`` surfaces every shortlisted row.
* Each per-row entry carries EXACTLY these 14 packet keys:
  ``event_id``, ``headline``, ``event_date``,
  ``current_primary_ticker``, ``flags``, ``reason``,
  ``manual_review_priority``, ``fast_to_clean_score``,
  ``fast_to_clean_reason``, ``proposed_primary_ticker``,
  ``proposed_benchmark``, ``proposed_mechanism_family``,
  ``ticker_rationale``, ``exclude_reason``.
* The five operator-input fields (``proposed_primary_ticker``,
  ``proposed_benchmark``, ``proposed_mechanism_family``,
  ``ticker_rationale``, ``exclude_reason``) are ALWAYS empty strings
  — the packet does not assign or propose tickers / mechanism
  families; those columns are operator-input slots.
* Candidates sort ``(-fast_to_clean_score, event_id)`` — higher
  scores surface first, ties broken by ascending event_id.
* CSV output format: header row matching the 14 keys in order,
  ``flags`` pipe-separated, ``\n`` line terminator.
* Recommended-next-action wording stays conservative — banned tokens
  include ``delete``, ``auto-correct``, ``auto fix``, ``automatic``,
  ``assign``, ``fix the``, ``propose``, ``replace``, ``correct``.
  ``fast_to_clean_reason`` for every emitted candidate is also
  banned-word-free.
* Read-only: default run does not import yfinance / market_check /
  market_data / price_cache / api / fastapi / routes.*.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_ticker_repair_packet as cli  # noqa: E402


_PACKET_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "flags",
    "reason",
    "manual_review_priority",
    "fast_to_clean_score",
    "fast_to_clean_reason",
    "proposed_primary_ticker",
    "proposed_benchmark",
    "proposed_mechanism_family",
    "ticker_rationale",
    "exclude_reason",
)


_BLANK_KEYS = (
    "proposed_primary_ticker",
    "proposed_benchmark",
    "proposed_mechanism_family",
    "ticker_rationale",
    "exclude_reason",
)


_BANNED_WORDS = (
    "delete",
    "auto-correct",
    "auto fix",
    "automatic",
    "assign",
    "fix the",
    "propose",
    "replace",
    "correct",
)


# ---------------------------------------------------------------------------
# Synthetic shortlist payloads + event-date maps
# ---------------------------------------------------------------------------


def _shortlist_candidate(
    *, event_id: int, priority: str, reason: str = "contaminated_fully_ready",
    headline: str | None = "Some headline", primary_ticker: str | None = "AAPL",
    flags: list[str] | None = None,
) -> dict:
    return {
        "event_id":               event_id,
        "headline":               headline,
        "primary_ticker":         primary_ticker,
        "flags":                  flags if flags is not None else ["driv_lit_off_topic"],
        "reason":                 reason,
        "manual_review_priority": priority,
    }


def _shortlist_payload(candidates: list[dict]) -> dict:
    by_priority = {"high": 0, "medium": 0, "low": 0}
    by_reason = {"missing_market_tickers": 0, "contaminated_fully_ready": 0}
    for c in candidates:
        by_priority[c["manual_review_priority"]] = (
            by_priority.get(c["manual_review_priority"], 0) + 1
        )
        by_reason[c["reason"]] = by_reason.get(c["reason"], 0) + 1
    return {
        "ok":                      True,
        "total_candidates":        len(candidates),
        "by_priority":             by_priority,
        "by_reason":               by_reason,
        "candidates":              list(candidates),
        "recommended_next_action": "synthetic",
    }


def _patch_seams(
    *, shortlist: dict, event_dates: dict[int, str | None] | None = None,
):
    event_dates = event_dates if event_dates is not None else {}
    return (
        patch.object(cli, "_run_repair_shortlist", return_value=shortlist),
        patch.object(cli, "_fetch_event_dates", return_value=event_dates),
    )


def _run(
    *, shortlist: dict | None = None,
    event_dates: dict[int, str | None] | None = None,
    **kwargs,
) -> dict:
    shortlist = shortlist if shortlist is not None else _shortlist_payload([])
    p1, p2 = _patch_seams(shortlist=shortlist, event_dates=event_dates)
    with p1, p2:
        return cli.summarize_repair_packet(**kwargs)


def _run_cli(
    argv: list[str],
    *, shortlist: dict | None = None,
    event_dates: dict[int, str | None] | None = None,
) -> tuple[int, str]:
    shortlist = shortlist if shortlist is not None else _shortlist_payload([])
    out = StringIO()
    p1, p2 = _patch_seams(shortlist=shortlist, event_dates=event_dates)
    with p1, p2:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Per-row contract
# ---------------------------------------------------------------------------


class TestPerRowContract(unittest.TestCase):
    def test_each_row_has_exactly_14_keys(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="high"),
            ]),
            event_dates={1: "2026-04-01", 2: "2026-04-02"},
            priority="high",
        )
        self.assertGreater(len(result["candidates"]), 0)
        for entry in result["candidates"]:
            self.assertEqual(set(entry.keys()), set(_PACKET_KEYS),
                             f"unexpected keys: {entry.keys()!r}")

    def test_blank_proposal_fields_are_empty_strings(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
            priority="high",
        )
        entry = result["candidates"][0]
        for k in _BLANK_KEYS:
            self.assertEqual(entry[k], "",
                             f"{k} must be blank string, got {entry[k]!r}")

    def test_event_date_enrichment_maps_correctly(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=10, priority="high"),
                _shortlist_candidate(event_id=20, priority="high"),
            ]),
            event_dates={10: "2026-03-01", 20: "2026-03-02"},
            priority="high",
        )
        by_id = {c["event_id"]: c for c in result["candidates"]}
        self.assertEqual(by_id[10]["event_date"], "2026-03-01")
        self.assertEqual(by_id[20]["event_date"], "2026-03-02")

    def test_event_date_missing_renders_as_none_in_json(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={},  # no event_date for event_id=1
            priority="high",
        )
        self.assertIsNone(result["candidates"][0]["event_date"])

    def test_current_primary_ticker_carries_through(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high",
                                     primary_ticker="DRIV"),
            ]),
            event_dates={1: "2026-04-01"},
            priority="high",
        )
        self.assertEqual(result["candidates"][0]["current_primary_ticker"], "DRIV")

    def test_current_primary_ticker_none_when_missing(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     primary_ticker=None,
                                     reason="missing_market_tickers",
                                     flags=["missing_market_tickers"]),
            ]),
            event_dates={1: "2026-04-01"},
            priority="all",
        )
        self.assertIsNone(result["candidates"][0]["current_primary_ticker"])


# ---------------------------------------------------------------------------
# Default priority filter
# ---------------------------------------------------------------------------


class TestPriorityFilter(unittest.TestCase):
    def test_default_filter_is_medium_only(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="low",
                                     flags=["mechanism_family_none"]),
            ]),
            event_dates={1: "x", 2: "y", 3: "z"},
        )
        self.assertEqual(
            [c["event_id"] for c in result["candidates"]], [2])
        self.assertEqual(result["priority_filter"], "medium")

    def test_priority_all_surfaces_all_buckets(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="low",
                                     flags=["mechanism_family_none"]),
            ]),
            event_dates={1: "x", 2: "y", 3: "z"},
            priority="all",
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(sorted(ids), [1, 2, 3])

    def test_priority_medium_filter(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="low",
                                     flags=["mechanism_family_none"]),
            ]),
            event_dates={1: "x", 2: "y", 3: "z"},
            priority="medium",
        )
        self.assertEqual(
            [c["event_id"] for c in result["candidates"]], [2])

    def test_total_candidates_in_filter_reflects_filtered_set(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="low",
                                     flags=["mechanism_family_none"]),
            ]),
            event_dates={1: "x", 2: "y", 3: "z"},
        )
        self.assertEqual(result["total_candidates_in_filter"], 1)


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder(unittest.TestCase):
    def test_sort_by_fast_to_clean_score_desc(self) -> None:
        # Mixed flag combinations so scores differ.  Default candidates
        # carry ``driv_lit_off_topic`` (a bonus); explicit overrides
        # carry penalty flags.  Verify scores are non-increasing and
        # ties break by ascending event_id.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=5, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=2, priority="high",
                                     flags=["driv_lit_off_topic"]),
                _shortlist_candidate(event_id=4, priority="low",
                                     flags=["mechanism_family_none"]),
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="high",
                                     flags=["driv_lit_off_topic"]),
            ]),
            event_dates={i: f"2026-04-{i:02d}" for i in range(1, 6)},
            priority="all",
        )
        # driv-bonus rows (2, 3) score highest; dup-penalty rows (1, 5)
        # middle; mechanism-family-none-only row (4) lowest.  Within
        # each tier, ascending event_id breaks ties.
        self.assertEqual(
            [c["event_id"] for c in result["candidates"]],
            [2, 3, 1, 5, 4],
        )
        scores = [c["fast_to_clean_score"] for c in result["candidates"]]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1],
                                    f"scores not non-increasing: {scores}")

    def test_score_ties_break_by_event_id_asc(self) -> None:
        # All rows identical (same flags, same enrichment) → identical
        # scores → tiebreak by ascending event_id.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=7, priority="high"),
                _shortlist_candidate(event_id=2, priority="high"),
                _shortlist_candidate(event_id=4, priority="high"),
            ]),
            event_dates={7: "x", 2: "y", 4: "z"},
            priority="high",
        )
        self.assertEqual(
            [c["event_id"] for c in result["candidates"]], [2, 4, 7])


# ---------------------------------------------------------------------------
# Limit truncates rows but not aggregate count
# ---------------------------------------------------------------------------


class TestLimitTruncation(unittest.TestCase):
    def test_limit_truncates_candidates_only(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=i, priority="high")
                for i in range(1, 11)
            ]),
            event_dates={i: f"2026-04-{i:02d}" for i in range(1, 11)},
            limit=3,
            priority="high",
        )
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["total_candidates_in_filter"], 10)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_recommended_action_mentions_manual_review(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "x"},
            priority="high",
        )
        self.assertIn("manual review",
                      result["recommended_next_action"].lower())

    def test_recommended_action_mentions_estimated_when_populated(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "x"},
            priority="high",
        )
        self.assertIn("estimated",
                      result["recommended_next_action"].lower())

    def test_recommended_action_avoids_banned_words(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "x"},
            priority="high",
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec,
                             f"banned word {w!r} in: {rec!r}")

    def test_empty_packet_recommendation_is_conservative(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([]),
            event_dates={},
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec,
                             f"banned word {w!r} in: {rec!r}")


# ---------------------------------------------------------------------------
# Fast-to-clean scoring
# ---------------------------------------------------------------------------


class TestFastToCleanScore(unittest.TestCase):
    def test_score_is_int_in_range_zero_to_ten(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={1: "2026-04-01"},
        )
        score = result["candidates"][0]["fast_to_clean_score"]
        self.assertIsInstance(score, int)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 10)

    def test_event_date_present_scores_higher_than_missing(self) -> None:
        with_date = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={1: "2026-04-01"},
        )
        without_date = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={},
        )
        self.assertGreater(
            with_date["candidates"][0]["fast_to_clean_score"],
            without_date["candidates"][0]["fast_to_clean_score"],
        )

    def test_plausible_headline_scores_higher_than_short(self) -> None:
        plausible = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="medium",
                    flags=["duplicate_date_ticker"],
                    headline="Bank of America announces dividend increase"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        short = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="medium",
                    flags=["duplicate_date_ticker"],
                    headline="x"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertGreater(
            plausible["candidates"][0]["fast_to_clean_score"],
            short["candidates"][0]["fast_to_clean_score"],
        )

    def test_local_off_topic_flag_lowers_score(self) -> None:
        with_penalty = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high",
                                     flags=["local_off_topic_headline"]),
            ]),
            event_dates={1: "2026-04-01"},
            priority="all",
        )
        with_bonus = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high",
                                     flags=["driv_lit_off_topic"]),
            ]),
            event_dates={1: "2026-04-01"},
            priority="all",
        )
        self.assertLess(
            with_penalty["candidates"][0]["fast_to_clean_score"],
            with_bonus["candidates"][0]["fast_to_clean_score"],
        )

    def test_duplicate_date_ticker_lowers_score(self) -> None:
        with_dup = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={1: "2026-04-01"},
        )
        with_missing = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["missing_market_tickers"]),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertLess(
            with_dup["candidates"][0]["fast_to_clean_score"],
            with_missing["candidates"][0]["fast_to_clean_score"],
        )

    def test_mechanism_family_none_only_lowers_score(self) -> None:
        only = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="low",
                                     flags=["mechanism_family_none"]),
            ]),
            event_dates={1: "2026-04-01"},
            priority="all",
        )
        accompanied = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="high",
                    flags=["mechanism_family_none", "driv_lit_off_topic"]),
            ]),
            event_dates={1: "2026-04-01"},
            priority="all",
        )
        self.assertLess(
            only["candidates"][0]["fast_to_clean_score"],
            accompanied["candidates"][0]["fast_to_clean_score"],
        )

    def test_missing_ticker_with_event_date_scores_high(self) -> None:
        # Clearest "fast to clean" path: missing_market_tickers + a
        # plausible headline + an event_date — operator just needs to
        # supply a primary ticker by hand.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="medium",
                    flags=["missing_market_tickers"],
                    primary_ticker=None,
                    headline="Bank of America announces dividend increase"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertGreaterEqual(
            result["candidates"][0]["fast_to_clean_score"], 7)

    def test_score_clamped_to_zero_floor(self) -> None:
        # Stack penalties; verify score never goes below zero.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="high",
                    flags=["local_off_topic_headline",
                           "duplicate_date_ticker",
                           "mechanism_family_none"],
                    primary_ticker=None,
                    headline="x"),
            ]),
            event_dates={},  # no event_date either
            priority="all",
        )
        self.assertGreaterEqual(
            result["candidates"][0]["fast_to_clean_score"], 0)


class TestFastToCleanReason(unittest.TestCase):
    def test_reason_is_string(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertIsInstance(
            result["candidates"][0]["fast_to_clean_reason"], str)
        self.assertGreater(
            len(result["candidates"][0]["fast_to_clean_reason"]), 0)

    def test_reason_is_banned_word_free_across_flag_combinations(self) -> None:
        flag_combos = [
            ["driv_lit_off_topic"],
            ["local_off_topic_headline"],
            ["duplicate_date_ticker"],
            ["mechanism_family_none"],
            ["missing_market_tickers"],
            ["driv_lit_off_topic", "mechanism_family_none"],
            ["duplicate_date_ticker", "mechanism_family_none"],
        ]
        for flags in flag_combos:
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(event_id=1, priority="medium",
                                         flags=flags),
                ]),
                event_dates={1: "2026-04-01"},
                priority="all",
            )
            reason = result["candidates"][0]["fast_to_clean_reason"].lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, reason,
                                 f"reason {reason!r} contains {w!r} for flags={flags}")


# ---------------------------------------------------------------------------
# Production-likeness filter (--production-like-only)
# ---------------------------------------------------------------------------


# Synthetic seed-phrase list patched into the seam so the filter
# tests don't depend on the canonical cleanup-report list contents.
_SYNTHETIC_SEED_PHRASES = (
    "macro shock test event",
    "opec slashes output",
    "fed speakers rotate",
    "tech ceo steps down",
    "turkey lira weakens",
    "fixture event",
)


def _patch_seed_phrases(phrases: tuple[str, ...]):
    return patch.object(cli, "_get_seed_like_phrases", return_value=phrases)


class TestProductionLikeOnlyFilter(unittest.TestCase):
    def test_flag_defaults_to_off_keeps_all_rows(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="medium",
                    flags=["missing_market_tickers"],
                    headline="Macro shock test event"),
                _shortlist_candidate(
                    event_id=2, priority="medium",
                    flags=["missing_market_tickers"],
                    headline="Bank of America announces dividend increase"),
            ]),
            event_dates={1: "2026-04-01", 2: "2026-04-02"},
        )
        ids = sorted(c["event_id"] for c in result["candidates"])
        self.assertEqual(ids, [1, 2])

    def test_flag_on_excludes_seed_phrase_rows(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                ]),
                event_dates={1: "2026-04-01", 2: "2026-04-02"},
                production_like_only=True,
            )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [2],
                         f"seed-phrase row leaked through filter: {ids}")

    def test_filter_is_case_insensitive(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="OPEC SLASHES OUTPUT BY 2 mbpd"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Fed Speakers Rotate on inflation commentary"),
                ]),
                event_dates={1: "2026-04-01", 2: "2026-04-02"},
                production_like_only=True,
            )
        self.assertEqual(result["candidates"], [])

    def test_filter_keeps_short_specific_real_headlines(self) -> None:
        # Short headlines that don't match any seed phrase must NOT be
        # filtered just because they are short.
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="GS Q4 EPS"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="JPM dividend"),
                ]),
                event_dates={1: "2026-04-01", 2: "2026-04-02"},
                production_like_only=True,
            )
        ids = sorted(c["event_id"] for c in result["candidates"])
        self.assertEqual(ids, [1, 2])

    def test_filter_keeps_blank_headlines(self) -> None:
        # A None / blank headline isn't seed leakage by itself —
        # operator should still see it for manual review.
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline=None),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline=""),
                ]),
                event_dates={1: "2026-04-01", 2: "2026-04-02"},
                production_like_only=True,
            )
        ids = sorted(c["event_id"] for c in result["candidates"])
        self.assertEqual(ids, [1, 2])

    def test_total_in_filter_reflects_post_filter_count(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                    _shortlist_candidate(
                        event_id=3, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="OPEC slashes output by 2 mbpd"),
                ]),
                event_dates={i: "2026-04-01" for i in range(1, 4)},
                production_like_only=True,
            )
        self.assertEqual(result["total_candidates_in_filter"], 1)

    def test_rows_filtered_from_review_packet_counts_seed_excludes(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="OPEC slashes output by 2 mbpd"),
                    _shortlist_candidate(
                        event_id=3, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                ]),
                event_dates={i: "2026-04-01" for i in range(1, 4)},
                production_like_only=True,
            )
        self.assertEqual(result["rows_filtered_from_review_packet"], 2)

    def test_rows_filtered_zero_when_flag_off(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="medium",
                    flags=["missing_market_tickers"],
                    headline="Macro shock test event"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(result["rows_filtered_from_review_packet"], 0)

    def test_production_like_only_active_field_present(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([]),
            event_dates={},
        )
        self.assertEqual(result["production_like_only_active"], False)

        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([]),
                event_dates={},
                production_like_only=True,
            )
        self.assertEqual(result["production_like_only_active"], True)

    def test_seed_phrase_seam_is_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_get_seed_like_phrases")))

    def test_seed_phrase_seam_resolves_canonical_lists(self) -> None:
        # Un-patched call returns a tuple of lowercase strings drawn
        # from the canonical archive-cleanup pattern lists.  Don't
        # assert the full contents (those are owned by the cleanup
        # report's tests); just spot-check a known live entry.
        phrases = cli._get_seed_like_phrases()
        self.assertIsInstance(phrases, tuple)
        self.assertGreater(len(phrases), 0)
        self.assertTrue(all(isinstance(p, str) for p in phrases))
        joined = "|".join(phrases).lower()
        self.assertIn("macro shock test event", joined)
        self.assertIn("opec slashes output", joined)


class TestProductionLikeOnlyCLI(unittest.TestCase):
    def test_flag_via_cli_excludes_seed_rows_in_json(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            rc, output = _run_cli(
                ["--json", "--priority", "medium", "--production-like-only"],
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                ]),
                event_dates={1: "x", 2: "y"},
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        ids = [c["event_id"] for c in parsed["candidates"]]
        self.assertEqual(ids, [2])
        self.assertEqual(parsed["production_like_only_active"], True)
        self.assertEqual(parsed["rows_filtered_from_review_packet"], 1)

    def test_flag_via_cli_csv_excludes_seed_rows(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            rc, output = _run_cli(
                ["--csv", "--priority", "medium", "--production-like-only"],
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                ]),
                event_dates={1: "x", 2: "y"},
            )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(tuple(header), _PACKET_KEYS)
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][_PACKET_KEYS.index("event_id")], "2")

    def test_recommended_action_mentions_filter_when_active(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                ]),
                event_dates={1: "x", 2: "y"},
                production_like_only=True,
            )
        rec = result["recommended_next_action"].lower()
        self.assertIn("filtered from review packet", rec)
        # No banned words leak in.
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec,
                             f"banned word {w!r} in recommendation: {rec!r}")


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_run_repair_shortlist_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_repair_shortlist")))

    def test_fetch_event_dates_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_event_dates")))

    def test_shortlist_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake_shortlist(*, db_path):
            captured["db_path"] = db_path
            return _shortlist_payload([])

        with patch.object(cli, "_run_repair_shortlist",
                          side_effect=fake_shortlist):
            with patch.object(cli, "_fetch_event_dates",
                              return_value={}):
                cli.summarize_repair_packet(db_path="/sentinel/path.db")
        self.assertEqual(captured.get("db_path"), "/sentinel/path.db")

    def test_event_dates_seam_called_with_filtered_event_ids(self) -> None:
        """Only filtered candidates' ids get sent to the DB lookup —
        no need to fetch event_date for rows we'll discard by priority.
        Default filter is now ``medium``; only the medium row should be
        sent to the seam.
        """
        captured: dict = {}

        def fake_dates(*, db_path, event_ids):
            captured["event_ids"] = list(event_ids)
            captured["db_path"] = db_path
            return {ev_id: "2026-04-01" for ev_id in event_ids}

        with patch.object(
            cli, "_run_repair_shortlist",
            return_value=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="low",
                                     flags=["mechanism_family_none"]),
            ]),
        ):
            with patch.object(cli, "_fetch_event_dates",
                              side_effect=fake_dates):
                cli.summarize_repair_packet()  # default medium
        self.assertEqual(sorted(captured["event_ids"]), [2])


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------


class TestCSVRendering(unittest.TestCase):
    def test_csv_header_matches_packet_keys_in_order(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(tuple(header), _PACKET_KEYS)

    def test_csv_flags_pipe_separated(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="high",
                    flags=["driv_lit_off_topic", "duplicate_date_ticker"],
                ),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        next(reader)  # header
        first_row = next(reader)
        flags_idx = _PACKET_KEYS.index("flags")
        self.assertEqual(first_row[flags_idx],
                         "driv_lit_off_topic|duplicate_date_ticker")

    def test_csv_blank_fields_are_empty_strings(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)  # header
        row = next(reader)
        for k in _BLANK_KEYS:
            self.assertEqual(row[_PACKET_KEYS.index(k)], "")

    def test_csv_uses_lf_line_terminator(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        # No \r\r\n — just \n
        self.assertNotIn("\r\r", output)

    def test_csv_quotes_headlines_with_commas(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="high",
                    headline="Apple, Inc. announces new product"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        # Round-trip through csv.reader to confirm the comma is preserved.
        reader = csv.reader(io.StringIO(output))
        next(reader)
        row = next(reader)
        self.assertEqual(row[_PACKET_KEYS.index("headline")],
                         "Apple, Inc. announces new product")


# ---------------------------------------------------------------------------
# JSON CLI
# ---------------------------------------------------------------------------


class TestJSONRendering(unittest.TestCase):
    def test_json_payload_has_candidates_list(self) -> None:
        rc, output = _run_cli(
            ["--json", "--priority", "high", "--limit", "20"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertIn("candidates", parsed)
        self.assertEqual(parsed["priority_filter"], "high")
        self.assertEqual(parsed["candidates"][0]["event_id"], 1)
        for k in _PACKET_KEYS:
            self.assertIn(k, parsed["candidates"][0])

    def test_csv_and_json_mutually_exclusive(self) -> None:
        # argparse should reject both flags simultaneously.
        rc, _ = _run_cli(
            ["--json", "--csv", "--priority", "high"],
            shortlist=_shortlist_payload([]),
            event_dates={},
        )
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# Read-only / import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance",
        "market_check",
        "market_data",
        "price_cache",
        "api",
        "fastapi",
    )

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        with patch.object(cli, "_run_repair_shortlist",
                          return_value=_shortlist_payload([])):
            with patch.object(cli, "_fetch_event_dates",
                              return_value={}):
                cli.summarize_repair_packet()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_default_priority_is_medium(self) -> None:
        rc, output = _run_cli(
            ["--json"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={1: "x", 2: "y"},
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["priority_filter"], "medium")
        self.assertEqual([c["event_id"] for c in parsed["candidates"]], [2])

    def test_text_mode_default_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        # Text rendering must mention manual review, never banned words.
        lower = output.lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, lower,
                             f"text rendering used banned word {w!r}")


# ---------------------------------------------------------------------------
# Stable export summary
# ---------------------------------------------------------------------------


_EXPORT_SUMMARY_KEYS = (
    "candidate_count",
    "rows_filtered_from_review_packet",
    "top_candidates",
)

_TOP_CANDIDATE_KEYS = ("event_id", "headline")


class TestExportSummary(unittest.TestCase):
    def test_export_summary_present_with_exactly_three_keys(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
            priority="high",
        )
        self.assertIn("export_summary", result)
        self.assertEqual(
            set(result["export_summary"].keys()),
            set(_EXPORT_SUMMARY_KEYS),
            f"unexpected export_summary keys: "
            f"{sorted(result['export_summary'].keys())}",
        )

    def test_candidate_count_equals_len_candidates(self) -> None:
        # Pin the invariant across several candidates / no truncation.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=i, priority="high")
                for i in range(1, 6)
            ]),
            event_dates={i: f"2026-04-{i:02d}" for i in range(1, 6)},
            priority="high",
        )
        self.assertEqual(
            result["export_summary"]["candidate_count"],
            len(result["candidates"]),
        )
        self.assertEqual(result["export_summary"]["candidate_count"], 5)

    def test_candidate_count_equals_len_candidates_after_limit(self) -> None:
        # Limit truncates candidates AND top_candidates symmetrically;
        # candidate_count tracks the post-truncation length, not the
        # filter count.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=i, priority="high")
                for i in range(1, 11)
            ]),
            event_dates={i: f"2026-04-{i:02d}" for i in range(1, 11)},
            priority="high",
            limit=4,
        )
        self.assertEqual(len(result["candidates"]), 4)
        self.assertEqual(result["export_summary"]["candidate_count"], 4)
        self.assertEqual(result["total_candidates_in_filter"], 10)

    def test_top_candidates_carries_only_id_and_headline(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high",
                                     headline="Bank of America Q4 EPS"),
            ]),
            event_dates={1: "2026-04-01"},
            priority="high",
        )
        top = result["export_summary"]["top_candidates"]
        self.assertEqual(len(top), 1)
        self.assertEqual(set(top[0].keys()), set(_TOP_CANDIDATE_KEYS))
        self.assertEqual(top[0]["event_id"], 1)
        self.assertEqual(top[0]["headline"], "Bank of America Q4 EPS")

    def test_top_candidates_ordering_matches_candidates(self) -> None:
        # Candidates are sorted by (-score, event_id) — top_candidates
        # must mirror that exact order so the summary stays a faithful
        # quote-friendly subset of the full list.
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=5, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=2, priority="high",
                                     flags=["driv_lit_off_topic"]),
                _shortlist_candidate(event_id=4, priority="low",
                                     flags=["mechanism_family_none"]),
                _shortlist_candidate(event_id=1, priority="medium",
                                     flags=["duplicate_date_ticker"]),
                _shortlist_candidate(event_id=3, priority="high",
                                     flags=["driv_lit_off_topic"]),
            ]),
            event_dates={i: f"2026-04-{i:02d}" for i in range(1, 6)},
            priority="all",
        )
        full_ids = [c["event_id"] for c in result["candidates"]]
        summary_ids = [c["event_id"]
                       for c in result["export_summary"]["top_candidates"]]
        self.assertEqual(summary_ids, full_ids)

    def test_top_candidates_length_equals_candidate_count(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=i, priority="high")
                for i in range(1, 8)
            ]),
            event_dates={i: f"2026-04-{i:02d}" for i in range(1, 8)},
            priority="high",
            limit=3,
        )
        self.assertEqual(
            len(result["export_summary"]["top_candidates"]),
            result["export_summary"]["candidate_count"],
        )

    def test_rows_filtered_mirrored_under_production_like_only(self) -> None:
        with _patch_seed_phrases(_SYNTHETIC_SEED_PHRASES):
            result = _run(
                shortlist=_shortlist_payload([
                    _shortlist_candidate(
                        event_id=1, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Macro shock test event"),
                    _shortlist_candidate(
                        event_id=2, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="OPEC slashes output by 2 mbpd"),
                    _shortlist_candidate(
                        event_id=3, priority="medium",
                        flags=["missing_market_tickers"],
                        headline="Bank of America announces dividend increase"),
                ]),
                event_dates={i: "2026-04-01" for i in range(1, 4)},
                production_like_only=True,
            )
        self.assertEqual(result["rows_filtered_from_review_packet"], 2)
        self.assertEqual(
            result["export_summary"]["rows_filtered_from_review_packet"],
            result["rows_filtered_from_review_packet"],
        )
        # Only the non-seed event survives into both lists.
        self.assertEqual(
            [c["event_id"] for c in result["candidates"]], [3])
        self.assertEqual(
            [c["event_id"]
             for c in result["export_summary"]["top_candidates"]],
            [3],
        )

    def test_empty_packet_summary_is_zeros_and_empty_list(self) -> None:
        result = _run(
            shortlist=_shortlist_payload([]),
            event_dates={},
        )
        self.assertEqual(result["export_summary"]["candidate_count"], 0)
        self.assertEqual(
            result["export_summary"]["rows_filtered_from_review_packet"], 0,
        )
        self.assertEqual(result["export_summary"]["top_candidates"], [])

    def test_top_candidates_carries_none_headline_unchanged(self) -> None:
        # A candidate with a missing headline should round-trip as
        # ``None`` in the summary too — no silent coercion to "".
        result = _run(
            shortlist=_shortlist_payload([
                _shortlist_candidate(
                    event_id=1, priority="medium",
                    flags=["missing_market_tickers"],
                    primary_ticker=None,
                    headline=None),
            ]),
            event_dates={1: "2026-04-01"},
            priority="all",
        )
        top = result["export_summary"]["top_candidates"]
        self.assertEqual(len(top), 1)
        self.assertIsNone(top[0]["headline"])

    def test_export_summary_emitted_in_json_cli(self) -> None:
        rc, output = _run_cli(
            ["--json", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertIn("export_summary", parsed)
        self.assertEqual(
            set(parsed["export_summary"].keys()),
            set(_EXPORT_SUMMARY_KEYS),
        )
        self.assertEqual(parsed["export_summary"]["candidate_count"], 1)


class TestCsvUnchangedByExportSummary(unittest.TestCase):
    """Regression guard: adding the JSON-only export_summary block must
    NOT add a column to the CSV worksheet — operator workflows depend
    on the 14-column schema being byte-stable.
    """

    def test_csv_header_is_still_exactly_fourteen_columns(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(len(header), 14)
        self.assertEqual(tuple(header), _PACKET_KEYS)

    def test_csv_row_is_still_exactly_fourteen_columns(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
                _shortlist_candidate(event_id=2, priority="high"),
            ]),
            event_dates={1: "2026-04-01", 2: "2026-04-02"},
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        next(reader)  # header
        for row in reader:
            self.assertEqual(len(row), 14,
                             f"CSV row has wrong column count: {row!r}")

    def test_csv_does_not_mention_export_summary(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--priority", "high"],
            shortlist=_shortlist_payload([
                _shortlist_candidate(event_id=1, priority="high"),
            ]),
            event_dates={1: "2026-04-01"},
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("export_summary", output)
        self.assertNotIn("top_candidates", output)
        self.assertNotIn("candidate_count", output)


if __name__ == "__main__":
    unittest.main()
