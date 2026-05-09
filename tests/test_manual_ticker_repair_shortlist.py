"""Tests for ``scripts/manual_ticker_repair_shortlist.py``.

Pin the contract:

* The shortlist consumes two upstream reports through patchable
  seams so unit tests can drive it with synthetic fixtures:
  ``_run_missing_tickers_report`` (missing-market-tickers source)
  and ``_run_contamination_report`` (contaminated fully-ready
  source).
* Each candidate carries ``event_id``, ``headline``,
  ``primary_ticker`` (None for the missing-tickers source bucket),
  ``flags``, ``reason``, and ``manual_review_priority``.
* Two reasons exist:
    - ``missing_market_tickers``   — events with no usable primary
                                     symbol.
    - ``contaminated_fully_ready`` — fully-ready events whose
                                     ticker assignment looks
                                     suspicious.
* Priority is derived purely from upstream flags:
    - ``high``   — at least one of ``driv_lit_off_topic`` or
                   ``local_off_topic_headline`` fired.
    - ``medium`` — missing-tickers row, OR contamination row whose
                   only ticker-relevance flag is
                   ``duplicate_date_ticker``.
    - ``low``    — contamination row with only
                   ``mechanism_family_none``.
* ``--limit`` truncates ``candidates`` only.  Aggregate counts
  (``total_candidates``, ``by_priority``, ``by_reason``) always
  reflect every shortlisted event.
* Conservative language: the recommended action mentions "manual
  review" but never "delete", "auto-correct", "auto fix",
  "automatic", "assign", or "fix the".
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

from scripts import manual_ticker_repair_shortlist as cli  # noqa: E402


_TOP_KEYS = (
    "ok",
    "total_candidates",
    "by_priority",
    "by_reason",
    "candidates",
    "recommended_next_action",
)


_PRIORITY_KEYS = ("high", "medium", "low")


_REASON_KEYS = (
    "missing_market_tickers",
    "contaminated_fully_ready",
)


_PER_CANDIDATE_KEYS = (
    "event_id",
    "headline",
    "primary_ticker",
    "flags",
    "reason",
    "manual_review_priority",
)


# ---------------------------------------------------------------------------
# Synthetic upstream payload helpers
# ---------------------------------------------------------------------------


def _missing_tickers_payload(events: list[dict]) -> dict:
    return {
        "total_events":                  max(len(events), 0),
        "events_missing_market_tickers": len(events),
        "events":                        events,
        "recommended_next_action":       "synthetic",
    }


def _missing_event(
    *, event_id: int, headline: str | None = "Unrelated headline",
) -> dict:
    return {
        "event_id":              event_id,
        "event_date":            "2026-04-15",
        "headline":              headline,
        "stage":                 "active",
        "persistence":           "high",
        "confidence":            "high",
        "suggested_next_action": "manual_review_required",
    }


def _contam_payload(examples: list[dict]) -> dict:
    return {
        "ok":                          True,
        "total_fully_ready":           len(examples),
        "suspicious_count":            len(examples),
        "duplicate_date_ticker_count": sum(
            1 for e in examples if "duplicate_date_ticker" in (e.get("flags") or [])
        ),
        "by_flag": {
            "driv_lit_off_topic":      sum(
                1 for e in examples
                if "driv_lit_off_topic" in (e.get("flags") or [])
            ),
            "mechanism_family_none":   sum(
                1 for e in examples
                if "mechanism_family_none" in (e.get("flags") or [])
            ),
            "duplicate_date_ticker":   sum(
                1 for e in examples
                if "duplicate_date_ticker" in (e.get("flags") or [])
            ),
            "local_off_topic_headline": sum(
                1 for e in examples
                if "local_off_topic_headline" in (e.get("flags") or [])
            ),
        },
        "examples":                examples,
        "recommended_next_action": "synthetic",
    }


def _contam_example(
    *,
    event_id: int,
    flags: list[str],
    primary_ticker: str | None = "DRIV",
    headline: str | None = "Murder arrest in Barnsley",
    event_date: str | None = "2026-04-06",
    mechanism_family: str | None = "policy_constraint",
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "flags":            flags,
    }


def _patch_missing(payload: dict):
    return patch.object(cli, "_run_missing_tickers_report", return_value=payload)


def _patch_contam(payload: dict):
    return patch.object(cli, "_run_contamination_report", return_value=payload)


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
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_by_priority_has_every_required_bucket(self) -> None:
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertIsInstance(result["by_priority"], dict)
        for key in _PRIORITY_KEYS:
            self.assertIn(key, result["by_priority"],
                          f"missing priority bucket: {key}")
            self.assertIsInstance(result["by_priority"][key], int)

    def test_by_reason_has_every_required_bucket(self) -> None:
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertIsInstance(result["by_reason"], dict)
        for key in _REASON_KEYS:
            self.assertIn(key, result["by_reason"],
                          f"missing reason bucket: {key}")
            self.assertIsInstance(result["by_reason"][key], int)

    def test_ok_is_true_on_clean_run(self) -> None:
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Empty payloads
# ---------------------------------------------------------------------------


class TestEmptyShortlist(unittest.TestCase):
    def test_no_upstream_events_yields_zero_candidates(self) -> None:
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["total_candidates"], 0)
        self.assertEqual(result["candidates"], [])
        for key in _PRIORITY_KEYS:
            self.assertEqual(result["by_priority"][key], 0)
        for key in _REASON_KEYS:
            self.assertEqual(result["by_reason"][key], 0)
        self.assertNotIn("manual review",
                         result["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# Reason: missing_market_tickers
# ---------------------------------------------------------------------------


class TestMissingTickersSource(unittest.TestCase):
    def test_missing_event_surfaces_as_medium_priority(self) -> None:
        events = [_missing_event(event_id=1, headline="Some headline")]
        with _patch_missing(_missing_tickers_payload(events)), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["total_candidates"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["event_id"], 1)
        self.assertEqual(c["reason"], "missing_market_tickers")
        self.assertEqual(c["manual_review_priority"], "medium")
        self.assertIsNone(c["primary_ticker"])
        self.assertEqual(c["headline"], "Some headline")
        self.assertIn("missing_market_tickers", c["flags"])

    def test_missing_event_count_reflected_in_by_reason(self) -> None:
        events = [_missing_event(event_id=eid) for eid in (1, 2, 3)]
        with _patch_missing(_missing_tickers_payload(events)), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["by_reason"]["missing_market_tickers"], 3)
        self.assertEqual(result["by_reason"]["contaminated_fully_ready"], 0)
        self.assertEqual(result["by_priority"]["medium"], 3)
        self.assertEqual(result["by_priority"]["high"], 0)
        self.assertEqual(result["by_priority"]["low"], 0)

    def test_invalid_event_id_is_skipped(self) -> None:
        # Defensive: upstream entries with non-int event_id are
        # dropped rather than crashing the shortlist.
        bad = {
            "event_id":              "not-an-int",
            "headline":              "Headline",
            "suggested_next_action": "manual_review_required",
        }
        good = _missing_event(event_id=2)
        with _patch_missing(_missing_tickers_payload([bad, good])), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["total_candidates"], 1)
        self.assertEqual(result["candidates"][0]["event_id"], 2)


# ---------------------------------------------------------------------------
# Reason: contaminated_fully_ready
# ---------------------------------------------------------------------------


class TestContaminatedSource(unittest.TestCase):
    def test_driv_lit_off_topic_is_high_priority(self) -> None:
        ex = _contam_example(
            event_id=10, flags=["driv_lit_off_topic"], primary_ticker="DRIV",
        )
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["total_candidates"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["reason"], "contaminated_fully_ready")
        self.assertEqual(c["manual_review_priority"], "high")
        self.assertEqual(c["primary_ticker"], "DRIV")
        self.assertIn("driv_lit_off_topic", c["flags"])

    def test_local_off_topic_headline_is_high_priority(self) -> None:
        ex = _contam_example(
            event_id=10, flags=["local_off_topic_headline"],
            primary_ticker="XOM",
        )
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["candidates"][0]["manual_review_priority"],
                         "high")

    def test_duplicate_date_ticker_only_is_medium_priority(self) -> None:
        ex = _contam_example(
            event_id=10, flags=["duplicate_date_ticker"],
            primary_ticker="XOM",
        )
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["candidates"][0]["manual_review_priority"],
                         "medium")

    def test_mechanism_family_none_only_is_low_priority(self) -> None:
        ex = _contam_example(
            event_id=10, flags=["mechanism_family_none"],
            primary_ticker="XOM",
        )
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["candidates"][0]["manual_review_priority"],
                         "low")

    def test_high_flag_dominates_other_flags(self) -> None:
        # Multi-flag row with a high-priority signal lands in high.
        ex = _contam_example(
            event_id=10,
            flags=[
                "driv_lit_off_topic",
                "duplicate_date_ticker",
                "mechanism_family_none",
            ],
            primary_ticker="DRIV",
        )
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["candidates"][0]["manual_review_priority"],
                         "high")
        self.assertCountEqual(
            result["candidates"][0]["flags"],
            ["driv_lit_off_topic", "duplicate_date_ticker",
             "mechanism_family_none"],
        )

    def test_medium_flag_dominates_low_flag(self) -> None:
        ex = _contam_example(
            event_id=10,
            flags=["duplicate_date_ticker", "mechanism_family_none"],
            primary_ticker="XOM",
        )
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["candidates"][0]["manual_review_priority"],
                         "medium")

    def test_contaminated_count_reflected_in_by_reason(self) -> None:
        examples = [
            _contam_example(event_id=1, flags=["driv_lit_off_topic"]),
            _contam_example(event_id=2, flags=["duplicate_date_ticker"]),
            _contam_example(event_id=3, flags=["mechanism_family_none"]),
        ]
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload(examples)):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["by_reason"]["contaminated_fully_ready"], 3)
        self.assertEqual(result["by_reason"]["missing_market_tickers"], 0)
        self.assertEqual(result["by_priority"]["high"],   1)
        self.assertEqual(result["by_priority"]["medium"], 1)
        self.assertEqual(result["by_priority"]["low"],    1)


# ---------------------------------------------------------------------------
# Combined population
# ---------------------------------------------------------------------------


class TestCombinedPopulation(unittest.TestCase):
    def test_both_sources_combined_into_single_candidate_list(self) -> None:
        missing = [_missing_event(event_id=1)]
        contam = [
            _contam_example(event_id=2, flags=["driv_lit_off_topic"],
                            primary_ticker="DRIV"),
        ]
        with _patch_missing(_missing_tickers_payload(missing)), \
             _patch_contam(_contam_payload(contam)):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["total_candidates"], 2)
        ids = {c["event_id"] for c in result["candidates"]}
        self.assertEqual(ids, {1, 2})

    def test_high_priority_appears_before_medium_appears_before_low(self) -> None:
        missing = [_missing_event(event_id=100)]   # medium
        contam = [
            _contam_example(event_id=50,  flags=["mechanism_family_none"],
                            primary_ticker="XOM"),                  # low
            _contam_example(event_id=10,  flags=["driv_lit_off_topic"],
                            primary_ticker="DRIV"),                 # high
        ]
        with _patch_missing(_missing_tickers_payload(missing)), \
             _patch_contam(_contam_payload(contam)):
            result = cli.summarize_repair_shortlist()
        priorities = [c["manual_review_priority"]
                      for c in result["candidates"]]
        # high block then medium block then low block
        self.assertEqual(
            priorities,
            sorted(priorities,
                   key=lambda p: {"high": 0, "medium": 1, "low": 2}[p]),
        )
        self.assertEqual(priorities[0], "high")
        self.assertEqual(priorities[-1], "low")

    def test_within_priority_bucket_sorted_by_event_id_ascending(self) -> None:
        contam = [
            _contam_example(event_id=eid, flags=["driv_lit_off_topic"],
                            primary_ticker="DRIV")
            for eid in (8, 2, 5, 1)
        ]
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload(contam)):
            result = cli.summarize_repair_shortlist()
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1, 2, 5, 8])


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_limit_truncates_candidates_only(self) -> None:
        contam = [
            _contam_example(event_id=eid, flags=["driv_lit_off_topic"],
                            primary_ticker="DRIV")
            for eid in range(1, 11)
        ]
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload(contam)):
            result = cli.summarize_repair_shortlist(limit=3)
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["total_candidates"], 10)
        self.assertEqual(result["by_priority"]["high"], 10)
        self.assertEqual(result["by_reason"]["contaminated_fully_ready"], 10)

    def test_negative_limit_clamps_to_zero(self) -> None:
        ex = _contam_example(event_id=1, flags=["driv_lit_off_topic"],
                             primary_ticker="DRIV")
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist(limit=-5)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["total_candidates"], 1)


# ---------------------------------------------------------------------------
# Candidate entry shape
# ---------------------------------------------------------------------------


class TestCandidateShape(unittest.TestCase):
    def test_every_candidate_has_required_keys(self) -> None:
        missing = [_missing_event(event_id=1)]
        contam = [
            _contam_example(event_id=2, flags=["driv_lit_off_topic"],
                            primary_ticker="DRIV"),
        ]
        with _patch_missing(_missing_tickers_payload(missing)), \
             _patch_contam(_contam_payload(contam)):
            result = cli.summarize_repair_shortlist()
        for c in result["candidates"]:
            for key in _PER_CANDIDATE_KEYS:
                self.assertIn(key, c, f"candidate missing key: {key}")
            self.assertIsInstance(c["flags"], list)

    def test_missing_source_carries_no_primary_ticker(self) -> None:
        events = [_missing_event(event_id=1)]
        with _patch_missing(_missing_tickers_payload(events)), \
             _patch_contam(_contam_payload([])):
            result = cli.summarize_repair_shortlist()
        self.assertIsNone(result["candidates"][0]["primary_ticker"])

    def test_contaminated_source_preserves_primary_ticker(self) -> None:
        ex = _contam_example(event_id=1, flags=["driv_lit_off_topic"],
                             primary_ticker="DRIV")
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        self.assertEqual(result["candidates"][0]["primary_ticker"], "DRIV")


# ---------------------------------------------------------------------------
# Conservative language
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    _BANNED = (
        "delete", "auto-correct", "auto correct", "auto-fix", "auto fix",
        "automatic", "fix the", "correct the", "assign ticker",
        "assigns tickers automatically",
    )

    def test_recommended_action_uses_review_language_when_candidates_exist(self) -> None:
        ex = _contam_example(event_id=1, flags=["driv_lit_off_topic"],
                             primary_ticker="DRIV")
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            result = cli.summarize_repair_shortlist()
        rec = result["recommended_next_action"].lower()
        self.assertIn("manual review", rec)

    def test_recommended_action_never_uses_destructive_or_auto_language(self) -> None:
        scenarios = [
            ([], []),
            ([_missing_event(event_id=1)], []),
            ([], [_contam_example(event_id=1,
                                  flags=["driv_lit_off_topic"],
                                  primary_ticker="DRIV")]),
            ([_missing_event(event_id=1)],
             [_contam_example(event_id=2,
                              flags=["mechanism_family_none"],
                              primary_ticker="XOM")]),
        ]
        for missing, contam in scenarios:
            with _patch_missing(_missing_tickers_payload(missing)), \
                 _patch_contam(_contam_payload(contam)):
                result = cli.summarize_repair_shortlist()
            rec = result["recommended_next_action"].lower()
            for banned in self._BANNED:
                self.assertNotIn(
                    banned, rec,
                    f"banned phrase {banned!r} appeared in: {rec!r}",
                )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestPureHelpers(unittest.TestCase):
    def test_priority_for_contamination_examples(self) -> None:
        self.assertEqual(
            cli._priority_for_contamination(["driv_lit_off_topic"]), "high")
        self.assertEqual(
            cli._priority_for_contamination(["local_off_topic_headline"]),
            "high")
        self.assertEqual(
            cli._priority_for_contamination(
                ["driv_lit_off_topic", "mechanism_family_none"]),
            "high")
        self.assertEqual(
            cli._priority_for_contamination(["duplicate_date_ticker"]),
            "medium")
        self.assertEqual(
            cli._priority_for_contamination(
                ["duplicate_date_ticker", "mechanism_family_none"]),
            "medium")
        self.assertEqual(
            cli._priority_for_contamination(["mechanism_family_none"]),
            "low")
        self.assertEqual(
            cli._priority_for_contamination([]), "low")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parseable_json(self) -> None:
        ex = _contam_example(event_id=1, flags=["driv_lit_off_topic"],
                             primary_ticker="DRIV")
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, parsed)

    def test_text_mode_includes_total_candidates(self) -> None:
        ex = _contam_example(event_id=1, flags=["driv_lit_off_topic"],
                             primary_ticker="DRIV")
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload([ex])):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("Total candidates", output)
        self.assertIn("manual review", output.lower())

    def test_limit_arg_caps_candidates(self) -> None:
        contam = [
            _contam_example(event_id=eid, flags=["driv_lit_off_topic"],
                            primary_ticker="DRIV")
            for eid in range(1, 6)
        ]
        with _patch_missing(_missing_tickers_payload([])), \
             _patch_contam(_contam_payload(contam)):
            rc, output = _run_cli(["--json", "--limit", "2"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(len(parsed["candidates"]), 2)
        self.assertEqual(parsed["total_candidates"], 5)


# ---------------------------------------------------------------------------
# End-to-end: real seams against a temp DB.
# ---------------------------------------------------------------------------


class TestEndToEndAgainstTempDb(unittest.TestCase):
    """Wire the un-patched seams against a synthetic SQLite DB to
    confirm the plumbing reaches the events table without
    provider/network/LLM calls.
    """

    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"repair_shortlist_e2e_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE events ("
                " id INTEGER PRIMARY KEY,"
                " event_date TEXT, headline TEXT,"
                " stage TEXT, persistence TEXT, confidence TEXT,"
                " market_tickers TEXT, mechanism_family TEXT)"
            )
            conn.execute(
                "CREATE TABLE price_cache ("
                " ticker TEXT, date TEXT, auto_adjust INTEGER)"
            )
            conn.commit()
        finally:
            conn.close()
        return path

    def test_runs_against_empty_temp_db_without_errors(self) -> None:
        path = self._make_temp_db()
        try:
            result = cli.summarize_repair_shortlist(db_path=path)
        finally:
            os.unlink(path)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["total_candidates"], 0)
        self.assertEqual(result["candidates"], [])

    def test_runs_against_temp_db_with_missing_ticker_event(self) -> None:
        path = self._make_temp_db()
        try:
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "INSERT INTO events"
                    " (id, event_date, headline, stage, persistence,"
                    "  confidence, market_tickers, mechanism_family)"
                    " VALUES"
                    " (1, '2026-04-06', 'Some headline',"
                    "  'active', 'high', 'high', '[]',"
                    "  'policy_constraint')"
                )
                conn.commit()
            finally:
                conn.close()
            result = cli.summarize_repair_shortlist(db_path=path)
        finally:
            os.unlink(path)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["total_candidates"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["event_id"], 1)
        self.assertEqual(c["reason"], "missing_market_tickers")
        self.assertEqual(c["manual_review_priority"], "medium")
        self.assertIsNone(c["primary_ticker"])


if __name__ == "__main__":
    unittest.main()
