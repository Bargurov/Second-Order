"""Tests for ``scripts/next_manual_repair_batch_selector.py``.

Pin the contract:

* The selector wraps two patchable seams —
  ``_run_repair_packet`` (calls
  :func:`scripts.manual_ticker_repair_packet.summarize_repair_packet`
  with ``priority="medium"`` and ``production_like_only=True``) and
  ``_run_sector_benchmark_suggestions`` (calls
  :func:`scripts.sector_benchmark_suggestion_report
  .summarize_sector_benchmark_suggestions`).  Tests patch both seams so
  unit coverage never hits a real DB.
* Twenty-four event_ids known to be already manually reviewed are
  excluded from the surfaced candidates.  The exclusion set is fixed
  in code as a frozenset; its size is pinned in a test.
* Per-row schema is EXACTLY 12 columns in this order:
  ``candidate_rank``, ``event_id``, ``headline``, ``event_date``,
  ``suggested_benchmark``, ``benchmark_confidence``,
  ``fast_to_clean_score``, ``proposed_primary_ticker``,
  ``proposed_benchmark``, ``proposed_mechanism_family``,
  ``ticker_rationale``, ``exclude_reason``.  The five operator-input
  columns are always empty strings.
* Order of operations: exclude reviewed event_ids → sort by
  ``(-fast_to_clean_score, event_id)`` → assign 1-based
  ``candidate_rank`` → truncate by ``--limit`` (default 10).
* ``benchmark_confidence`` is the rename of the sector report's
  ``confidence`` field.  Missing event_ids in the sector lookup fall
  back to ``("SPY", "none")`` defensively.
* CSV output: header = the 12 column names in order; rows terminate
  with ``\n``.
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

from scripts import next_manual_repair_batch_selector as selector  # noqa: E402


# ---------------------------------------------------------------------------
# Per-row column contract (pinned order)
# ---------------------------------------------------------------------------


_PACKET_KEYS = (
    "candidate_rank",
    "event_id",
    "headline",
    "event_date",
    "suggested_benchmark",
    "benchmark_confidence",
    "fast_to_clean_score",
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

# The 24 event_ids the operator has already manually reviewed.
_EXPECTED_EXCLUDED_EVENT_IDS = (
    4, 6, 8, 9,
    46, 47, 49, 51,
    60, 64, 73,
    112,
    153, 154, 160,
    206, 207, 208, 216, 220, 226, 231, 237,
    281,
)


# ---------------------------------------------------------------------------
# Synthetic packet + sector payloads
# ---------------------------------------------------------------------------


def _packet_candidate(
    *, event_id: int, fast_to_clean_score: int = 7,
    headline: str | None = "Some headline",
    event_date: str | None = "2026-04-15",
    primary_ticker: str | None = "AAPL",
    flags: list[str] | None = None,
    manual_review_priority: str = "medium",
) -> dict:
    return {
        "event_id":                 event_id,
        "headline":                 headline,
        "event_date":               event_date,
        "current_primary_ticker":   primary_ticker,
        "flags":                    flags if flags is not None else [],
        "reason":                   "missing_market_tickers",
        "manual_review_priority":   manual_review_priority,
        "fast_to_clean_score":      fast_to_clean_score,
        "fast_to_clean_reason":     "has_event_date|plausible_headline",
        "proposed_primary_ticker":   "",
        "proposed_benchmark":        "",
        "proposed_mechanism_family": "",
        "ticker_rationale":          "",
        "exclude_reason":            "",
    }


def _packet_payload(candidates: list[dict]) -> dict:
    return {
        "ok":                              True,
        "priority_filter":                 "medium",
        "production_like_only_active":     True,
        "rows_filtered_from_review_packet": 0,
        "total_candidates_in_filter":      len(candidates),
        "candidates":                      list(candidates),
        "export_summary": {
            "candidate_count":                  len(candidates),
            "rows_filtered_from_review_packet": 0,
            "top_candidates": [
                {"event_id": c["event_id"], "headline": c["headline"]}
                for c in candidates
            ],
        },
        "recommended_next_action":         "synthetic",
    }


def _sector_suggestion(
    *, event_id: int, suggested_benchmark: str = "SPY",
    confidence: str = "none",
    headline: str | None = "Some headline",
) -> dict:
    return {
        "event_id":               event_id,
        "headline":               headline,
        "event_date":             "2026-04-15",
        "current_primary_ticker": None,
        "manual_review_priority": "medium",
        "flags":                  [],
        "suggested_sector":       "broad",
        "suggested_benchmark":    suggested_benchmark,
        "confidence":             confidence,
        "rationale":              "no_signal|fallback_broad_market",
        "needs_manual_review":    confidence in ("low", "none"),
    }


def _sector_payload(suggestions: list[dict]) -> dict:
    agg = {"high": 0, "medium": 0, "low": 0, "none": 0}
    for s in suggestions:
        agg[s["confidence"]] = agg.get(s["confidence"], 0) + 1
    return {
        "ok":                       True,
        "candidate_count":          len(suggestions),
        "suggestions":              list(suggestions),
        "confidence":               agg,
        "needs_manual_review":      sum(1 for s in suggestions
                                        if s["needs_manual_review"]),
        "recommended_next_action":  "synthetic",
    }


def _patch_seams(*, packet: dict, sector: dict):
    return (
        patch.object(selector, "_run_repair_packet", return_value=packet),
        patch.object(selector, "_run_sector_benchmark_suggestions",
                     return_value=sector),
    )


def _run(*, packet: dict | None = None, sector: dict | None = None,
         **kwargs) -> dict:
    packet = packet if packet is not None else _packet_payload([])
    sector = sector if sector is not None else _sector_payload([])
    p1, p2 = _patch_seams(packet=packet, sector=sector)
    with p1, p2:
        return selector.summarize_next_manual_repair_batch(**kwargs)


def _run_cli(argv: list[str], *, packet: dict | None = None,
             sector: dict | None = None) -> tuple[int, str]:
    packet = packet if packet is not None else _packet_payload([])
    sector = sector if sector is not None else _sector_payload([])
    out = StringIO()
    p1, p2 = _patch_seams(packet=packet, sector=sector)
    with p1, p2:
        try:
            rc = selector.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Excluded event ids (constant + count)
# ---------------------------------------------------------------------------


class TestExcludedEventIds(unittest.TestCase):
    def test_excluded_set_is_frozenset_of_int(self) -> None:
        self.assertIsInstance(selector._EXCLUDED_EVENT_IDS, frozenset)
        for v in selector._EXCLUDED_EVENT_IDS:
            self.assertIsInstance(v, int)

    def test_excluded_set_has_exactly_24_event_ids(self) -> None:
        # Pinned size: any future change to the list breaks this test
        # so reviewers notice the cohort change.
        self.assertEqual(len(selector._EXCLUDED_EVENT_IDS), 24)

    def test_excluded_set_matches_spec(self) -> None:
        self.assertEqual(
            selector._EXCLUDED_EVENT_IDS,
            frozenset(_EXPECTED_EXCLUDED_EVENT_IDS),
        )


# ---------------------------------------------------------------------------
# Ranking + sort
# ---------------------------------------------------------------------------


class TestRanking(unittest.TestCase):
    def test_candidates_ranked_one_through_n(self) -> None:
        # Three candidates → ranks 1, 2, 3.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=10, fast_to_clean_score=9),
                _packet_candidate(event_id=11, fast_to_clean_score=8),
                _packet_candidate(event_id=12, fast_to_clean_score=7),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=10),
                _sector_suggestion(event_id=11),
                _sector_suggestion(event_id=12),
            ]),
        )
        ranks = [c["candidate_rank"] for c in result["candidates"]]
        self.assertEqual(ranks, [1, 2, 3])

    def test_sort_by_fast_to_clean_score_desc(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=11, fast_to_clean_score=5),
                _packet_candidate(event_id=12, fast_to_clean_score=10),
                _packet_candidate(event_id=13, fast_to_clean_score=7),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=11),
                _sector_suggestion(event_id=12),
                _sector_suggestion(event_id=13),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [12, 13, 11])
        scores = [c["fast_to_clean_score"] for c in result["candidates"]]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_score_ties_break_by_event_id_asc(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=33, fast_to_clean_score=8),
                _packet_candidate(event_id=11, fast_to_clean_score=8),
                _packet_candidate(event_id=22, fast_to_clean_score=8),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=11),
                _sector_suggestion(event_id=22),
                _sector_suggestion(event_id=33),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [11, 22, 33])


# ---------------------------------------------------------------------------
# Exclusion of reviewed event ids
# ---------------------------------------------------------------------------


class TestExclusion(unittest.TestCase):
    def test_excluded_event_ids_never_appear_in_candidates(self) -> None:
        # Mix excluded and non-excluded ids.  All excluded must be
        # filtered out regardless of score.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=153, fast_to_clean_score=10),
                _packet_candidate(event_id=999, fast_to_clean_score=5),
                _packet_candidate(event_id=281, fast_to_clean_score=10),
                _packet_candidate(event_id=998, fast_to_clean_score=4),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=998),
                _sector_suggestion(event_id=999),
            ]),
        )
        ids = {c["event_id"] for c in result["candidates"]}
        self.assertTrue(ids.isdisjoint(selector._EXCLUDED_EVENT_IDS))
        self.assertEqual(ids, {998, 999})

    def test_aggregate_counts_track_exclusion(self) -> None:
        # 4 packet candidates, 2 excluded → upstream=4, after exclusion=2.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=4),    # excluded
                _packet_candidate(event_id=6),    # excluded
                _packet_candidate(event_id=900),
                _packet_candidate(event_id=901),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=900),
                _sector_suggestion(event_id=901),
            ]),
        )
        self.assertEqual(result["upstream_packet_candidate_count"], 4)
        self.assertEqual(result["reviewed_exclusion_set_count"],    24)
        self.assertEqual(
            result["excluded_from_current_packet_count"], 2,
        )
        self.assertEqual(result["candidates_after_exclusion"],      2)
        self.assertEqual(len(result["candidates"]),                 2)

    def test_excluded_ids_filtered_before_limit_truncation(self) -> None:
        # If we truncated first, an excluded id at the top would
        # consume a slot.  Verify exclusion happens BEFORE truncation
        # by stuffing the top-scoring slots with excluded ids.
        excluded_top = [
            _packet_candidate(event_id=ev_id, fast_to_clean_score=10)
            for ev_id in (4, 6, 8, 9, 46)
        ]
        kept = [
            _packet_candidate(event_id=ev_id, fast_to_clean_score=8)
            for ev_id in (700, 701, 702)
        ]
        result = _run(
            packet=_packet_payload(excluded_top + kept),
            sector=_sector_payload([
                _sector_suggestion(event_id=ev) for ev in (700, 701, 702)
            ]),
            limit=3,
        )
        # Three slots, all filled with non-excluded ids despite the
        # higher-scoring excluded leaders.
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [700, 701, 702])
        self.assertEqual(result["reviewed_exclusion_set_count"], 24)
        self.assertEqual(
            result["excluded_from_current_packet_count"], 5,
        )


# ---------------------------------------------------------------------------
# Per-row schema
# ---------------------------------------------------------------------------


class TestPerRowSchema(unittest.TestCase):
    def test_each_row_has_exactly_twelve_keys(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=999),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=999),
            ]),
        )
        self.assertEqual(len(result["candidates"]), 1)
        entry = result["candidates"][0]
        self.assertEqual(set(entry.keys()), set(_PACKET_KEYS))

    def test_blank_operator_columns_are_empty_strings(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=999),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=999, suggested_benchmark="XLE",
                                   confidence="medium"),
            ]),
        )
        entry = result["candidates"][0]
        for k in _BLANK_KEYS:
            self.assertEqual(entry[k], "",
                             f"{k} must be blank string, got {entry[k]!r}")

    def test_required_inspection_fields_carry_through(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(
                    event_id=999, fast_to_clean_score=9,
                    headline="Bank of America announces dividend increase",
                    event_date="2026-04-15",
                ),
            ]),
            sector=_sector_payload([
                _sector_suggestion(
                    event_id=999, suggested_benchmark="XLF",
                    confidence="medium",
                ),
            ]),
        )
        entry = result["candidates"][0]
        self.assertEqual(entry["candidate_rank"],     1)
        self.assertEqual(entry["event_id"],           999)
        self.assertEqual(entry["headline"],
                         "Bank of America announces dividend increase")
        self.assertEqual(entry["event_date"],         "2026-04-15")
        self.assertEqual(entry["suggested_benchmark"], "XLF")
        self.assertEqual(entry["benchmark_confidence"], "medium")
        self.assertEqual(entry["fast_to_clean_score"], 9)


# ---------------------------------------------------------------------------
# Sector lookup join
# ---------------------------------------------------------------------------


class TestSectorLookup(unittest.TestCase):
    def test_benchmark_and_confidence_joined_by_event_id(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=10),
                _packet_candidate(event_id=20),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=10, suggested_benchmark="XLE",
                                   confidence="high"),
                _sector_suggestion(event_id=20, suggested_benchmark="XLK",
                                   confidence="medium"),
            ]),
        )
        by_id = {c["event_id"]: c for c in result["candidates"]}
        self.assertEqual(by_id[10]["suggested_benchmark"],   "XLE")
        self.assertEqual(by_id[10]["benchmark_confidence"],  "high")
        self.assertEqual(by_id[20]["suggested_benchmark"],   "XLK")
        self.assertEqual(by_id[20]["benchmark_confidence"],  "medium")

    def test_missing_sector_entry_falls_back_to_spy_none(self) -> None:
        # event 999 in packet but absent from sector report — must
        # fall back to ``("SPY", "none")`` defensively.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=999),
            ]),
            sector=_sector_payload([]),
        )
        entry = result["candidates"][0]
        self.assertEqual(entry["suggested_benchmark"],   "SPY")
        self.assertEqual(entry["benchmark_confidence"],  "none")

    def test_sector_field_renamed_from_confidence_to_benchmark_confidence(self) -> None:
        # The sector seam carries the field as ``confidence``; the
        # selector renames it to ``benchmark_confidence`` per spec.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=999),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=999, suggested_benchmark="XLE",
                                   confidence="high"),
            ]),
        )
        entry = result["candidates"][0]
        self.assertIn("benchmark_confidence", entry)
        self.assertNotIn("confidence", entry)


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_default_limit_is_ten(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=ev_id) for ev_id in range(900, 920)
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=ev_id) for ev_id in range(900, 920)
            ]),
        )
        self.assertEqual(len(result["candidates"]), 10)
        self.assertEqual(result["candidates_after_exclusion"], 20)

    def test_limit_truncates_candidates_only(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=ev_id) for ev_id in range(900, 905)
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=ev_id) for ev_id in range(900, 905)
            ]),
            limit=2,
        )
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["candidates_after_exclusion"], 5)

    def test_negative_limit_clamps_to_zero(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=900),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=900),
            ]),
            limit=-1,
        )
        self.assertEqual(len(result["candidates"]), 0)


# ---------------------------------------------------------------------------
# Seam contracts
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_packet_seam_exists_and_callable(self) -> None:
        self.assertTrue(callable(getattr(selector, "_run_repair_packet")))

    def test_sector_seam_exists_and_callable(self) -> None:
        self.assertTrue(callable(
            getattr(selector, "_run_sector_benchmark_suggestions")))

    def test_packet_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake_packet(**kwargs):
            captured.update(kwargs)
            return _packet_payload([])

        with patch.object(selector, "_run_repair_packet",
                          side_effect=fake_packet):
            with patch.object(selector, "_run_sector_benchmark_suggestions",
                              return_value=_sector_payload([])):
                selector.summarize_next_manual_repair_batch(
                    db_path="/sentinel/path.db",
                )
        self.assertEqual(captured.get("db_path"), "/sentinel/path.db")

    def test_sector_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake_sector(**kwargs):
            captured.update(kwargs)
            return _sector_payload([])

        with patch.object(selector, "_run_repair_packet",
                          return_value=_packet_payload([])):
            with patch.object(selector, "_run_sector_benchmark_suggestions",
                              side_effect=fake_sector):
                selector.summarize_next_manual_repair_batch(
                    db_path="/sentinel/path.db",
                )
        self.assertEqual(captured.get("db_path"), "/sentinel/path.db")

    def test_packet_seam_pins_priority_medium_and_production_like_only(self) -> None:
        """The default-path call to the packet must pin
        ``priority='medium'`` and ``production_like_only=True`` —
        otherwise a future default change in the packet silently alters
        this script's cohort.
        """
        # Verify the un-patched seam targets those kwargs.  We patch
        # ``summarize_repair_packet`` itself at its origin module so
        # the seam's downstream call surface is captured.
        from scripts import manual_ticker_repair_packet as mtrp
        captured: dict = {}

        def fake_summary(**kwargs):
            captured.update(kwargs)
            return _packet_payload([])

        with patch.object(mtrp, "summarize_repair_packet",
                          side_effect=fake_summary):
            selector._run_repair_packet(db_path=None)

        self.assertEqual(captured.get("priority"),             "medium")
        self.assertEqual(captured.get("production_like_only"), True)


# ---------------------------------------------------------------------------
# Top-level JSON contract
# ---------------------------------------------------------------------------


_TOP_KEYS = (
    "ok",
    "limit",
    "excluded_event_ids",
    "reviewed_exclusion_set_count",
    "excluded_from_current_packet_count",
    "upstream_packet_candidate_count",
    "candidates_after_exclusion",
    "candidates",
    "recommended_next_action",
)


class TestTopLevelShape(unittest.TestCase):
    def test_top_level_carries_required_keys(self) -> None:
        result = _run()
        for k in _TOP_KEYS:
            self.assertIn(k, result, f"missing top-level key: {k}")

    def test_excluded_event_ids_emitted_as_sorted_list(self) -> None:
        result = _run()
        ids = result["excluded_event_ids"]
        self.assertIsInstance(ids, list)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), set(_EXPECTED_EXCLUDED_EVENT_IDS))


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_recommendation_is_banned_word_free(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=900),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=900),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec, f"banned word {w!r} in: {rec!r}")

    def test_empty_packet_recommendation_is_banned_word_free(self) -> None:
        result = _run()
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec)


# ---------------------------------------------------------------------------
# CLI: JSON
# ---------------------------------------------------------------------------


class TestJSONCli(unittest.TestCase):
    def test_json_output_has_top_level_and_per_row_keys(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "10"],
            packet=_packet_payload([
                _packet_candidate(event_id=ev_id) for ev_id in range(900, 905)
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=ev_id) for ev_id in range(900, 905)
            ]),
        )
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for k in _TOP_KEYS:
            self.assertIn(k, body)
        self.assertEqual(len(body["candidates"]), 5)
        for entry in body["candidates"]:
            self.assertEqual(set(entry.keys()), set(_PACKET_KEYS))

    def test_json_csv_mutually_exclusive(self) -> None:
        rc, _ = _run_cli(["--json", "--csv"])
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# CLI: CSV
# ---------------------------------------------------------------------------


class TestCsvCli(unittest.TestCase):
    def test_csv_header_is_twelve_columns_in_spec_order(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--limit", "10"],
            packet=_packet_payload([
                _packet_candidate(event_id=900),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=900),
            ]),
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(len(header), 12)
        self.assertEqual(tuple(header), _PACKET_KEYS)

    def test_csv_row_count_equals_candidates(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--limit", "3"],
            packet=_packet_payload([
                _packet_candidate(event_id=ev_id) for ev_id in range(900, 905)
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=ev_id) for ev_id in range(900, 905)
            ]),
        )
        rows = list(csv.reader(io.StringIO(output)))
        self.assertEqual(len(rows), 4)  # header + 3
        for row in rows[1:]:
            self.assertEqual(len(row), 12)

    def test_csv_blank_columns_emit_empty_strings(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--limit", "1"],
            packet=_packet_payload([
                _packet_candidate(event_id=900),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=900),
            ]),
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)  # header
        row = next(reader)
        for k in _BLANK_KEYS:
            self.assertEqual(row[_PACKET_KEYS.index(k)], "")

    def test_csv_uses_lf_line_terminator(self) -> None:
        rc, output = _run_cli(
            ["--csv", "--limit", "1"],
            packet=_packet_payload([
                _packet_candidate(event_id=900),
            ]),
            sector=_sector_payload([
                _sector_suggestion(event_id=900),
            ]),
        )
        self.assertNotIn("\r\r", output)


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
        with patch.object(selector, "_run_repair_packet",
                          return_value=_packet_payload([])):
            with patch.object(selector, "_run_sector_benchmark_suggestions",
                              return_value=_sector_payload([])):
                selector.summarize_next_manual_repair_batch()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


# ---------------------------------------------------------------------------
# Operator output guard: never assigns tickers
# ---------------------------------------------------------------------------


class TestNeverAssignsTickers(unittest.TestCase):
    def test_operator_columns_stay_blank_even_when_packet_carries_proposed(self) -> None:
        """If the upstream packet ever surfaces a non-blank
        ``proposed_*`` field (it shouldn't, but defensively), the
        selector must still emit blank operator columns — the selector
        does not propagate proposed values into its own per-row schema.
        """
        candidate = _packet_candidate(event_id=999)
        # Tamper with the upstream payload to simulate the bad path.
        candidate["proposed_primary_ticker"] = "ZZZZ"  # synthetic poison
        result = _run(
            packet=_packet_payload([candidate]),
            sector=_sector_payload([_sector_suggestion(event_id=999)]),
        )
        entry = result["candidates"][0]
        for k in _BLANK_KEYS:
            self.assertEqual(entry[k], "",
                             f"{k} leaked from upstream: {entry[k]!r}")


if __name__ == "__main__":
    unittest.main()
