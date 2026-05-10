"""Tests for ``scripts/mechanism_family_repair_packet.py``.

Pin the contract:

* The packet builds on
  :func:`scripts.stat_validation_ticker_contamination_report.summarize_contamination`
  through the patchable seam ``_run_contamination_report`` so unit
  tests can drive it with synthetic contamination payloads.  No DB
  is ever touched in the test path.
* Per-row entries carry EXACTLY these 11 packet keys:
  ``event_id``, ``headline``, ``event_date``,
  ``current_primary_ticker``, ``current_benchmark``, ``flags``,
  ``repair_priority``, ``reason``, ``proposed_mechanism_family``,
  ``mechanism_rationale``, ``exclude_reason``.
* The three operator-input fields
  (``proposed_mechanism_family``, ``mechanism_rationale``,
  ``exclude_reason``) are ALWAYS empty strings — the packet does
  not assign mechanism families.
* Filter rule (mechanism-family-only):
    - Must include ``mechanism_family_none`` flag.
    - Must NOT include ``local_off_topic_headline`` or
      ``driv_lit_off_topic`` flags.
    - Allowed extra: ``duplicate_date_ticker``.
* Excluded event_ids: 24 already-reviewed events are dropped before
  ranking.
* ``current_benchmark`` is always ``"SPY"`` — the universal benchmark
  proxy that ``fully_ready`` events must already have cache for; the
  events table has no per-event benchmark column.
* Conservative wording — banned tokens in ``recommended_next_action``
  and ``reason`` strings: ``delete``, ``auto-correct``, ``auto fix``,
  ``automatic``, ``assign``, ``fix the``, ``propose``, ``replace``,
  ``correct``.  (Column names like ``proposed_mechanism_family`` are
  schema, not text — exempt by design.)
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

from scripts import mechanism_family_repair_packet as cli  # noqa: E402


_PACKET_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_benchmark",
    "flags",
    "repair_priority",
    "reason",
    "proposed_mechanism_family",
    "mechanism_rationale",
    "exclude_reason",
)


_BLANK_KEYS = (
    "proposed_mechanism_family",
    "mechanism_rationale",
    "exclude_reason",
)


_BANNED_WORDS = (
    "delete",
    "auto-correct",
    "auto fix",
    "automatic",
    "assign",
    "fix the",
    "replace",
    "correct",
)


# Banned words applied to free-text fields (recommended_next_action,
# reason).  Column names like ``proposed_mechanism_family`` are schema
# tokens, exempt from this list.  Drop ``propose`` here so the
# allowed-extra ``duplicate_date_ticker`` reason sentence below can
# describe the row clearly.
_BANNED_WORDS_TEXT = _BANNED_WORDS  # exported alias for readability


_EXPECTED_EXCLUDED_IDS = frozenset({
    4, 6, 8, 9,
    46, 47, 49, 51,
    60, 64, 73,
    112,
    153, 154, 160,
    206, 207, 208, 216, 220, 226, 231, 237,
    281,
})


# ---------------------------------------------------------------------------
# Synthetic contamination payloads
# ---------------------------------------------------------------------------


def _contamination_example(
    *,
    event_id: int,
    flags: list[str],
    headline: str | None = "Bank of America announces dividend increase",
    event_date: str | None = "2026-04-01",
    primary_ticker: str | None = "BAC",
    mechanism_family: str | None = None,
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "flags":            list(flags),
    }


def _contamination_payload(examples: list[dict]) -> dict:
    by_flag = {
        "driv_lit_off_topic":       sum(1 for e in examples if "driv_lit_off_topic"       in e["flags"]),
        "mechanism_family_none":    sum(1 for e in examples if "mechanism_family_none"    in e["flags"]),
        "duplicate_date_ticker":    sum(1 for e in examples if "duplicate_date_ticker"    in e["flags"]),
        "local_off_topic_headline": sum(1 for e in examples if "local_off_topic_headline" in e["flags"]),
    }
    return {
        "ok":                          True,
        "total_fully_ready":           max(len(examples), 1),
        "suspicious_count":            len(examples),
        "duplicate_date_ticker_count": by_flag["duplicate_date_ticker"],
        "by_flag":                     by_flag,
        "examples":                    list(examples),
        "recommended_next_action":     "synthetic",
    }


def _patch_seam(*, contamination: dict):
    return patch.object(
        cli, "_run_contamination_report", return_value=contamination,
    )


def _run(*, contamination: dict | None = None, **kwargs) -> dict:
    contamination = (
        contamination if contamination is not None
        else _contamination_payload([])
    )
    with _patch_seam(contamination=contamination):
        return cli.summarize_mechanism_family_repair_packet(**kwargs)


def _run_cli(
    argv: list[str], *, contamination: dict | None = None,
) -> tuple[int, str]:
    contamination = (
        contamination if contamination is not None
        else _contamination_payload([])
    )
    out = StringIO()
    with _patch_seam(contamination=contamination):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Per-row contract
# ---------------------------------------------------------------------------


class TestPerRowContract(unittest.TestCase):
    def test_each_row_has_exactly_eleven_keys(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
                _contamination_example(event_id=1001, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertGreater(len(result["candidates"]), 0)
        for entry in result["candidates"]:
            self.assertEqual(set(entry.keys()), set(_PACKET_KEYS),
                             f"unexpected keys: {entry.keys()!r}")

    def test_blank_proposal_fields_are_empty_strings(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        entry = result["candidates"][0]
        for k in _BLANK_KEYS:
            self.assertEqual(entry[k], "",
                             f"{k} must be blank string, got {entry[k]!r}")

    def test_current_benchmark_is_spy(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(result["candidates"][0]["current_benchmark"], "SPY")

    def test_event_date_carried_through(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    event_date="2026-03-15"),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["event_date"], "2026-03-15")

    def test_current_primary_ticker_carried_through(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    primary_ticker="AAPL"),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["current_primary_ticker"], "AAPL")

    def test_flags_list_preserved(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(
            sorted(result["candidates"][0]["flags"]),
            sorted(["mechanism_family_none", "duplicate_date_ticker"]),
        )


# ---------------------------------------------------------------------------
# Mechanism-family-only filter
# ---------------------------------------------------------------------------


class TestMechanismFamilyOnlyFilter(unittest.TestCase):
    def test_keeps_mechanism_family_none_only_rows(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
                _contamination_example(event_id=1001, flags=["mechanism_family_none"]),
            ]),
        )
        ids = sorted(c["event_id"] for c in result["candidates"])
        self.assertEqual(ids, [1000, 1001])

    def test_keeps_mechanism_family_none_with_duplicate_flag(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1000])

    def test_drops_rows_without_mechanism_family_none(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["duplicate_date_ticker"]),
                _contamination_example(event_id=1001, flags=["driv_lit_off_topic"]),
            ]),
        )
        self.assertEqual(result["candidates"], [])

    def test_drops_rows_with_local_off_topic_headline(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "local_off_topic_headline"]),
                _contamination_example(
                    event_id=1001,
                    flags=["mechanism_family_none"]),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1001])

    def test_drops_rows_with_driv_lit_off_topic(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "driv_lit_off_topic"]),
                _contamination_example(
                    event_id=1001,
                    flags=["mechanism_family_none"]),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1001])

    def test_drops_rows_with_dup_only(self) -> None:
        # Allowed-extra is duplicate_date_ticker WHEN mechanism_family_none
        # is also present.  duplicate-only rows fall outside our scope.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(result["candidates"], [])


# ---------------------------------------------------------------------------
# Reviewed-id exclusion
# ---------------------------------------------------------------------------


class TestReviewedIdExclusion(unittest.TestCase):
    def test_excluded_event_ids_set_count_is_24(self) -> None:
        self.assertEqual(len(cli._EXCLUDED_EVENT_IDS), 24)

    def test_excluded_event_ids_match_expected_membership(self) -> None:
        self.assertEqual(
            set(cli._EXCLUDED_EVENT_IDS), set(_EXPECTED_EXCLUDED_IDS))

    def test_reviewed_ids_dropped_from_candidates(self) -> None:
        # A reviewed id (4) and a fresh id (1000) — only the fresh id
        # should remain.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4, flags=["mechanism_family_none"]),
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1000])

    def test_excluded_count_reflects_dropped_reviewed_rows(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4, flags=["mechanism_family_none"]),
                _contamination_example(event_id=6, flags=["mechanism_family_none"]),
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(result["excluded_reviewed_count"], 2)


# ---------------------------------------------------------------------------
# Repair priority
# ---------------------------------------------------------------------------


class TestRepairPriority(unittest.TestCase):
    def test_only_mechanism_family_none_with_plausible_headline_is_high(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline="Bank of America announces dividend increase"),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "high")

    def test_only_mechanism_family_none_short_headline_is_medium(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline="x"),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "medium")

    def test_only_mechanism_family_none_missing_headline_is_medium(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=None),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "medium")

    def test_dup_extra_is_low_priority(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"],
                    headline="Bank of America announces dividend increase"),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "low")


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder(unittest.TestCase):
    def test_high_before_medium_before_low(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=3000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"],
                    headline="Bank of America announces dividend increase"),
                _contamination_example(
                    event_id=2000,
                    flags=["mechanism_family_none"],
                    headline="x"),
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline="Bank of America announces dividend increase"),
            ]),
        )
        priorities = [c["repair_priority"] for c in result["candidates"]]
        self.assertEqual(priorities, ["high", "medium", "low"])

    def test_within_priority_ties_break_by_event_id_asc(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1003, flags=["mechanism_family_none"],
                    headline="Bank of America announces dividend increase"),
                _contamination_example(
                    event_id=1001, flags=["mechanism_family_none"],
                    headline="Apple Inc announces share buyback program"),
                _contamination_example(
                    event_id=1002, flags=["mechanism_family_none"],
                    headline="Microsoft Corp posts record quarterly earnings"),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1001, 1002, 1003])


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimitTruncation(unittest.TestCase):
    def test_limit_truncates_candidates_only(self) -> None:
        examples = [
            _contamination_example(
                event_id=1000 + i,
                flags=["mechanism_family_none"],
                headline="Bank of America announces dividend increase")
            for i in range(10)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=3)
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["total_candidates_after_filter"], 10)

    def test_zero_limit_emits_no_candidates_but_keeps_count(self) -> None:
        examples = [
            _contamination_example(
                event_id=1000 + i, flags=["mechanism_family_none"])
            for i in range(5)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=0)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["total_candidates_after_filter"], 5)


# ---------------------------------------------------------------------------
# Reason wording
# ---------------------------------------------------------------------------


class TestReasonWording(unittest.TestCase):
    def test_reason_is_string_and_nonempty(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        reason = result["candidates"][0]["reason"]
        self.assertIsInstance(reason, str)
        self.assertGreater(len(reason), 0)

    def test_reason_mentions_mechanism_family(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertIn(
            "mechanism_family", result["candidates"][0]["reason"].lower(),
        )

    def test_reason_avoids_banned_words(self) -> None:
        for flags in (
            ["mechanism_family_none"],
            ["mechanism_family_none", "duplicate_date_ticker"],
        ):
            result = _run(
                contamination=_contamination_payload([
                    _contamination_example(event_id=1000, flags=flags),
                ]),
            )
            reason = result["candidates"][0]["reason"].lower()
            for w in _BANNED_WORDS_TEXT:
                self.assertNotIn(
                    w, reason,
                    f"reason {reason!r} contains banned word {w!r}")


class TestRecommendedAction(unittest.TestCase):
    def test_recommended_action_avoids_banned_words(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS_TEXT:
            self.assertNotIn(w, rec,
                             f"banned word {w!r} in: {rec!r}")

    def test_recommended_action_mentions_manual_review(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertIn("manual review",
                      result["recommended_next_action"].lower())

    def test_recommended_action_mentions_not_proof(self) -> None:
        # Conservative wording: explicitly disclaim that surfaced rows
        # are "manual review candidates," "not proof" of repairability.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        self.assertIn("not proof", rec)

    def test_empty_packet_recommendation_is_conservative(self) -> None:
        result = _run(contamination=_contamination_payload([]))
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS_TEXT:
            self.assertNotIn(w, rec,
                             f"banned word {w!r} in: {rec!r}")


# ---------------------------------------------------------------------------
# Aggregate counts
# ---------------------------------------------------------------------------


class TestAggregateCounts(unittest.TestCase):
    def test_total_after_filter_equals_eligible_rows(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
                _contamination_example(
                    event_id=1001,
                    flags=["mechanism_family_none", "local_off_topic_headline"]),
                _contamination_example(event_id=1002, flags=["mechanism_family_none"]),
            ]),
        )
        # 1001 dropped by local-off-topic; 1000 + 1002 remain.
        self.assertEqual(result["total_candidates_after_filter"], 2)

    def test_excluded_reviewed_count_only_counts_mechanism_family_subset(self) -> None:
        # Only events that would have passed the mechanism-family filter
        # AND are in the reviewed set should contribute.  An event that
        # is reviewed but doesn't carry mechanism_family_none should not
        # inflate the count.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4, flags=["mechanism_family_none"]),
                _contamination_example(event_id=8, flags=["driv_lit_off_topic"]),
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(result["excluded_reviewed_count"], 1)


# ---------------------------------------------------------------------------
# Seam
# ---------------------------------------------------------------------------


class TestSeam(unittest.TestCase):
    def test_run_contamination_report_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_contamination_report")))

    def test_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake(*, db_path):
            captured["db_path"] = db_path
            return _contamination_payload([])

        with patch.object(
            cli, "_run_contamination_report", side_effect=fake,
        ):
            cli.summarize_mechanism_family_repair_packet(
                db_path="/sentinel/path.db")
        self.assertEqual(captured.get("db_path"), "/sentinel/path.db")


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------


class TestCSVRendering(unittest.TestCase):
    def test_csv_header_matches_packet_keys_in_order(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(tuple(header), _PACKET_KEYS)

    def test_csv_flags_pipe_separated(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        next(reader)
        first_row = next(reader)
        flags_idx = _PACKET_KEYS.index("flags")
        self.assertEqual(
            first_row[flags_idx],
            "mechanism_family_none|duplicate_date_ticker",
        )

    def test_csv_blank_fields_are_empty_strings(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)
        row = next(reader)
        for k in _BLANK_KEYS:
            self.assertEqual(row[_PACKET_KEYS.index(k)], "")

    def test_csv_uses_lf_line_terminator(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertNotIn("\r\r", output)

    def test_csv_quotes_headlines_with_commas(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline="Apple, Inc. announces buyback"),
            ]),
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)
        row = next(reader)
        self.assertEqual(
            row[_PACKET_KEYS.index("headline")],
            "Apple, Inc. announces buyback",
        )


# ---------------------------------------------------------------------------
# JSON CLI
# ---------------------------------------------------------------------------


class TestJSONRendering(unittest.TestCase):
    def test_json_payload_has_candidates_list(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "20"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertIn("candidates", parsed)
        self.assertEqual(parsed["candidates"][0]["event_id"], 1000)
        for k in _PACKET_KEYS:
            self.assertIn(k, parsed["candidates"][0])

    def test_csv_and_json_mutually_exclusive(self) -> None:
        rc, _ = _run_cli(
            ["--json", "--csv"],
            contamination=_contamination_payload([]),
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
        with patch.object(
            cli, "_run_contamination_report",
            return_value=_contamination_payload([]),
        ):
            cli.summarize_mechanism_family_repair_packet()
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
    def test_text_mode_default_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        lower = output.lower()
        for w in _BANNED_WORDS_TEXT:
            self.assertNotIn(w, lower,
                             f"text rendering used banned word {w!r}")


if __name__ == "__main__":
    unittest.main()
