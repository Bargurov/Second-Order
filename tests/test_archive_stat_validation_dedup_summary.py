"""Tests for ``scripts/archive_stat_validation_dedup_summary.py``.

Pin the contract:

* The script reuses the archive validation runner's payload (via the
  patchable :func:`_run_validation` seam) to identify per-record
  ``(event_id, ticker, horizon, sar, p_value, fdr_q)`` tuples, then
  reads ``event_date`` for those events via the patchable
  :func:`_load_event_dates` seam.
* Records sharing ``(event_date, primary_ticker, horizon)`` are
  collapsed to a single canonical (smallest ``event_id``) representative
  in the deduped cohort.
* ``records_count`` reflects the raw runner cohort;
  ``effective_unique_records_count`` reflects the deduped cohort;
  ``duplicate_records_count`` and ``duplicate_groups_count`` are
  derived from the difference.
* ``qvalue_change`` re-runs Benjamini-Hochberg on the deduped cohort's
  p-values at the same alpha and reports per-record significance flips.
  Pin both directions: ``groups_gaining_significance`` and
  ``groups_losing_significance``.
* ``top_abs_sar`` ranks the deduped cohort by ``|sar|`` descending,
  caps at ``--limit``, and surfaces both ``raw_fdr_q`` (from the runner
  payload) and ``deduped_fdr_q`` (from the re-run BH adjustment).
* Conservative language: ``recommended_next_action`` never uses
  alpha-extraction or proof-of-causality phrasing.
* The script does NOT edit the archive — read-only by construction.
* No provider, yfinance, market_check, market_data, LLM, or FastAPI
  seam is touched.
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
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import archive_stat_validation_dedup_summary as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic payload helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    event_id:        int,
    ticker:          str = "AAPL",
    horizon:         int = 5,
    headline:        str | None = None,
    abnormal_return: float = 0.01,
    sar:             float = 0.5,
    ci_low:          float = -1.0,
    ci_high:         float = 1.0,
    p_value:         float = 0.5,
    fdr_q:           float = 0.5,
    interpretation:  str = "no_evidence",
) -> dict[str, Any]:
    """Build one runner-shaped per-record example.

    Mirrors the example schema documented in
    ``scripts/archive_stat_validation_run.py``.
    """
    return {
        "event_id":         event_id,
        "headline":         headline if headline is not None else f"Event {event_id}",
        "ticker":           ticker,
        "horizon":          horizon,
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "ci_low":           ci_low,
        "ci_high":          ci_high,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "interpretation":   interpretation,
    }


def _make_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a record list into the runner payload envelope.

    The dedup summary inspects ``examples`` and ``errors`` — every other
    runner field is ignored and can be left at default-shaped stubs.
    """
    return {
        "ok":                  True,
        "events_evaluated":    len({r["event_id"] for r in records}),
        "records_count":       len(records),
        "significant_count":   sum(
            1 for r in records
            if isinstance(r.get("fdr_q"), (int, float))
            and r["fdr_q"] <= 0.05
        ),
        "by_horizon":          {},
        "by_mechanism_family": {},
        "errors":              [],
        "examples":            list(records),
        "config":              {},
        "recommended_next_action": "",
    }


def _patch_seams(*, payload: dict[str, Any], event_dates: dict[int, str]):
    """Return a context manager that patches both seams together."""
    return _SeamPatcher(payload=payload, event_dates=event_dates)


class _SeamPatcher:

    def __init__(
        self,
        *,
        payload:     dict[str, Any],
        event_dates: dict[int, str],
    ) -> None:
        self._payload = payload
        self._event_dates = event_dates

    def __enter__(self):
        self._p1 = patch.object(
            cli, "_run_validation",
            return_value=self._payload,
        )
        self._p2 = patch.object(
            cli, "_load_event_dates",
            return_value=self._event_dates,
        )
        self._p1.start()
        self._p2.start()
        return self

    def __exit__(self, *exc):
        self._p2.stop()
        self._p1.stop()
        return False


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):

    def test_module_exposes_main(self) -> None:
        self.assertTrue(callable(cli.main))

    def test_module_exposes_summarize_dedup(self) -> None:
        self.assertTrue(callable(cli.summarize_dedup))


# ---------------------------------------------------------------------------
# Empty cohort
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):

    def test_empty_payload_returns_zero_counts(self) -> None:
        with _patch_seams(payload=_make_payload([]), event_dates={}):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertTrue(report["ok"])
        self.assertEqual(report["records_count"], 0)
        self.assertEqual(report["effective_unique_records_count"], 0)
        self.assertEqual(report["duplicate_records_count"], 0)
        self.assertEqual(report["duplicate_groups_count"], 0)
        self.assertEqual(report["top_abs_sar"], [])

    def test_empty_payload_recommends_no_records(self) -> None:
        with _patch_seams(payload=_make_payload([]), event_dates={}):
            report = cli.summarize_dedup(db_path=None, limit=10)
        action = report["recommended_next_action"]
        self.assertIn("no records", action.lower())


# ---------------------------------------------------------------------------
# No-duplicate cohort — every record gets a distinct dedup key
# ---------------------------------------------------------------------------


class TestNoDuplicates(unittest.TestCase):

    def setUp(self) -> None:
        self.records = [
            _make_record(event_id=1, ticker="AAPL", horizon=1,  sar=0.4, p_value=0.4, fdr_q=0.4),
            _make_record(event_id=2, ticker="MSFT", horizon=5,  sar=0.6, p_value=0.5, fdr_q=0.5),
            _make_record(event_id=3, ticker="GOOG", horizon=20, sar=0.8, p_value=0.6, fdr_q=0.6),
        ]
        self.event_dates = {
            1: "2026-01-10",
            2: "2026-01-11",
            3: "2026-01-12",
        }

    def test_records_count_matches_unique_count(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertEqual(report["records_count"], 3)
        self.assertEqual(report["effective_unique_records_count"], 3)
        self.assertEqual(report["duplicate_records_count"], 0)
        self.assertEqual(report["duplicate_groups_count"], 0)

    def test_no_duplicates_has_no_qvalue_change(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertFalse(report["qvalue_change"]["any_change"])
        self.assertEqual(
            report["qvalue_change"]["groups_gaining_significance"], 0,
        )
        self.assertEqual(
            report["qvalue_change"]["groups_losing_significance"], 0,
        )

    def test_no_duplicates_recommends_unique(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertIn("unique", report["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# Duplicate-collapse — three records share a dedup key, one is distinct
# ---------------------------------------------------------------------------


class TestDuplicateCollapse(unittest.TestCase):

    def setUp(self) -> None:
        # Three records share (2026-01-03, AAPL, 5); one record is
        # distinct on (2026-01-02, AAPL, 1).
        self.records = [
            _make_record(event_id=1, ticker="AAPL", horizon=1, sar=2.5, p_value=0.025, fdr_q=0.10),
            _make_record(event_id=2, ticker="AAPL", horizon=5, sar=0.5, p_value=0.3,   fdr_q=0.30),
            _make_record(event_id=3, ticker="AAPL", horizon=5, sar=0.5, p_value=0.3,   fdr_q=0.30),
            _make_record(event_id=4, ticker="AAPL", horizon=5, sar=0.5, p_value=0.3,   fdr_q=0.30),
        ]
        self.event_dates = {
            1: "2026-01-02",
            2: "2026-01-03",
            3: "2026-01-03",
            4: "2026-01-03",
        }

    def test_records_count_reflects_raw_cohort(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertEqual(report["records_count"], 4)

    def test_effective_unique_records_count_collapses_duplicates(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        # Distinct dedup keys: (2026-01-02,AAPL,1) and (2026-01-03,AAPL,5).
        self.assertEqual(report["effective_unique_records_count"], 2)

    def test_duplicate_counts_are_derived(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertEqual(report["duplicate_records_count"], 2)
        self.assertEqual(report["duplicate_groups_count"], 1)

    def test_by_horizon_split_records_and_unique(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        by_h = report["by_horizon"]
        self.assertIn("1", by_h)
        self.assertIn("5", by_h)
        self.assertEqual(by_h["1"]["records_count"], 1)
        self.assertEqual(by_h["1"]["effective_unique_records_count"], 1)
        self.assertEqual(by_h["5"]["records_count"], 3)
        self.assertEqual(by_h["5"]["effective_unique_records_count"], 1)

    def test_by_horizon_keys_are_strings(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        for key in report["by_horizon"].keys():
            self.assertIsInstance(key, str)


# ---------------------------------------------------------------------------
# Q-value change — deduplication can promote a record to significance
# when duplicate p-values inflate ``m`` in the BH denominator.
# ---------------------------------------------------------------------------


class TestQValueFlip(unittest.TestCase):

    def setUp(self) -> None:
        # B (event_id=1) has p=0.025 and a raw fdr_q of 0.10 (NOT
        # significant at alpha=0.05) because A1/A2/A3 (p=0.3 each, all
        # share the same dedup key (2026-01-03, AAPL, 5)) inflate m
        # to 4 in the runner's BH cohort.
        # After deduplication, the cohort shrinks to [B, A_canonical]
        # with deduped p-values [0.025, 0.3].  BH at m=2 gives B a
        # deduped q of 0.05 (SIGNIFICANT at alpha=0.05) — the gain
        # comes purely from removing the multiplicity inflation.
        self.records = [
            _make_record(event_id=1, ticker="AAPL", horizon=1, sar=2.5, p_value=0.025, fdr_q=0.10),
            _make_record(event_id=2, ticker="AAPL", horizon=5, sar=0.5, p_value=0.3,   fdr_q=0.30),
            _make_record(event_id=3, ticker="AAPL", horizon=5, sar=0.5, p_value=0.3,   fdr_q=0.30),
            _make_record(event_id=4, ticker="AAPL", horizon=5, sar=0.5, p_value=0.3,   fdr_q=0.30),
        ]
        self.event_dates = {
            1: "2026-01-02",
            2: "2026-01-03",
            3: "2026-01-03",
            4: "2026-01-03",
        }

    def test_groups_gaining_significance_counts_the_promoted_record(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        self.assertEqual(
            report["qvalue_change"]["groups_gaining_significance"], 1,
            f"expected B (p=0.025) to flip to significant under "
            f"deduplication; got {report['qvalue_change']!r}",
        )

    def test_no_groups_lose_significance_in_this_fixture(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        self.assertEqual(
            report["qvalue_change"]["groups_losing_significance"], 0,
        )

    def test_any_change_true_when_groups_flip(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        self.assertTrue(report["qvalue_change"]["any_change"])

    def test_raw_significant_records_pin_input_state(self) -> None:
        # In the raw cohort none of the supplied fdr_q values are at or
        # below alpha=0.05, so the raw significance count is zero.
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        self.assertEqual(
            report["qvalue_change"]["raw_significant_records"], 0,
        )

    def test_deduped_significant_unique_count_matches_post_bh(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        self.assertEqual(
            report["qvalue_change"]["deduped_significant_unique_records"], 1,
        )

    def test_recommended_next_action_warns_when_verdicts_change(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        action = report["recommended_next_action"].lower()
        self.assertIn("change", action)


# ---------------------------------------------------------------------------
# Top |SAR| ranking — deduped cohort, descending by absolute value.
# ---------------------------------------------------------------------------


_TOP_FIELDS = (
    "event_id",
    "event_date",
    "ticker",
    "horizon",
    "headline",
    "sar",
    "abs_sar",
    "p_value",
    "raw_fdr_q",
    "deduped_fdr_q",
)


class TestTopAbsSar(unittest.TestCase):

    def setUp(self) -> None:
        # A range of |SAR| magnitudes; one duplicate group to confirm
        # only the canonical representative appears in top_abs_sar.
        self.records = [
            _make_record(event_id=10, ticker="AAA", horizon=1, sar= 3.5, p_value=0.01, fdr_q=0.04),
            _make_record(event_id=20, ticker="BBB", horizon=1, sar=-4.2, p_value=0.02, fdr_q=0.05),
            _make_record(event_id=30, ticker="CCC", horizon=1, sar= 1.0, p_value=0.4,  fdr_q=0.4),
            _make_record(event_id=40, ticker="DDD", horizon=5, sar= 2.0, p_value=0.1,  fdr_q=0.2),
            _make_record(event_id=41, ticker="DDD", horizon=5, sar= 2.0, p_value=0.1,  fdr_q=0.2),
        ]
        self.event_dates = {
            10: "2026-02-01",
            20: "2026-02-02",
            30: "2026-02-03",
            40: "2026-02-04",
            41: "2026-02-04",  # duplicate of 40
        }

    def test_top_abs_sar_sorted_by_magnitude_descending(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        magnitudes = [entry["abs_sar"] for entry in report["top_abs_sar"]]
        self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))

    def test_top_abs_sar_omits_duplicate_record(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        event_ids = [entry["event_id"] for entry in report["top_abs_sar"]]
        # event_id 41 is the duplicate; only the canonical (40) survives.
        self.assertNotIn(41, event_ids)
        self.assertIn(40, event_ids)

    def test_top_abs_sar_first_entry_is_largest_magnitude(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        first = report["top_abs_sar"][0]
        # event_id 20 has |sar| = 4.2, the largest magnitude in the cohort.
        self.assertEqual(first["event_id"], 20)
        self.assertAlmostEqual(first["abs_sar"], 4.2)

    def test_top_abs_sar_carries_all_required_fields(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        for entry in report["top_abs_sar"]:
            for field in _TOP_FIELDS:
                self.assertIn(
                    field, entry, f"missing field {field!r}: {entry!r}"
                )

    def test_top_abs_sar_capped_at_limit(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=2)
        self.assertEqual(len(report["top_abs_sar"]), 2)

    def test_top_abs_sar_includes_event_date_from_seam(self) -> None:
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        for entry in report["top_abs_sar"]:
            ev_id = entry["event_id"]
            self.assertEqual(
                entry["event_date"], self.event_dates.get(ev_id),
            )


# ---------------------------------------------------------------------------
# Records with missing dedup-key components — must not collapse against
# anything else; treated as distinct entries in the unique cohort.
# ---------------------------------------------------------------------------


class TestKeylessRecords(unittest.TestCase):

    def test_record_without_event_date_is_kept_distinct(self) -> None:
        records = [
            _make_record(event_id=1, ticker="AAPL", horizon=1, p_value=0.1, fdr_q=0.1),
            _make_record(event_id=2, ticker="AAPL", horizon=1, p_value=0.1, fdr_q=0.1),
        ]
        # event_id 1 has no event_date; event_id 2 does — they cannot
        # share a dedup key without dates, so neither is collapsed.
        event_dates = {2: "2026-03-01"}
        with _patch_seams(
            payload=_make_payload(records), event_dates=event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertEqual(report["records_count"], 2)
        self.assertEqual(report["effective_unique_records_count"], 2)
        self.assertEqual(report["duplicate_records_count"], 0)
        self.assertEqual(report["duplicate_groups_count"], 0)

    def test_record_without_ticker_is_kept_distinct(self) -> None:
        records = [
            _make_record(event_id=1, ticker="",     horizon=1, p_value=0.1, fdr_q=0.1),
            _make_record(event_id=2, ticker="AAPL", horizon=1, p_value=0.1, fdr_q=0.1),
        ]
        event_dates = {1: "2026-03-01", 2: "2026-03-01"}
        with _patch_seams(
            payload=_make_payload(records), event_dates=event_dates,
        ):
            report = cli.summarize_dedup(db_path=None, limit=10)
        self.assertEqual(report["effective_unique_records_count"], 2)


# ---------------------------------------------------------------------------
# Conservative-language constraint — recommended_next_action must not
# claim "alpha generated", "proof of", or other extraction language.
# ---------------------------------------------------------------------------


_FORBIDDEN_PHRASES = (
    "alpha generated",
    "alpha-generated",
    "generates alpha",
    "proof of",
    "proves that",
    "proven",
    "guaranteed",
    "causal proof",
)


class TestConservativeLanguage(unittest.TestCase):

    def test_no_records_action_avoids_forbidden_phrases(self) -> None:
        with _patch_seams(payload=_make_payload([]), event_dates={}):
            report = cli.summarize_dedup(db_path=None, limit=5)
        action = report["recommended_next_action"].lower()
        for phrase in _FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, action)

    def test_with_flip_action_avoids_forbidden_phrases(self) -> None:
        records = [
            _make_record(event_id=1, ticker="AAPL", horizon=1, p_value=0.025, fdr_q=0.10),
            _make_record(event_id=2, ticker="AAPL", horizon=5, p_value=0.3,   fdr_q=0.30),
            _make_record(event_id=3, ticker="AAPL", horizon=5, p_value=0.3,   fdr_q=0.30),
            _make_record(event_id=4, ticker="AAPL", horizon=5, p_value=0.3,   fdr_q=0.30),
        ]
        event_dates = {
            1: "2026-04-01",
            2: "2026-04-02",
            3: "2026-04-02",
            4: "2026-04-02",
        }
        with _patch_seams(payload=_make_payload(records), event_dates=event_dates):
            report = cli.summarize_dedup(db_path=None, limit=10, alpha=0.05)
        action = report["recommended_next_action"].lower()
        for phrase in _FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, action)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def setUp(self) -> None:
        self.records = [
            _make_record(event_id=1, ticker="AAPL", horizon=1, p_value=0.025, fdr_q=0.10, sar=2.5),
            _make_record(event_id=2, ticker="AAPL", horizon=5, p_value=0.3,   fdr_q=0.30, sar=0.5),
            _make_record(event_id=3, ticker="AAPL", horizon=5, p_value=0.3,   fdr_q=0.30, sar=0.5),
        ]
        self.event_dates = {
            1: "2026-05-01",
            2: "2026-05-02",
            3: "2026-05-02",
        }

    def test_main_json_emits_valid_payload(self) -> None:
        out = StringIO()
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            code = cli.main(["--json", "--limit", "5"], out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        for key in (
            "ok", "records_count", "effective_unique_records_count",
            "duplicate_records_count", "duplicate_groups_count",
            "by_horizon", "qvalue_change", "top_abs_sar",
            "recommended_next_action",
        ):
            self.assertIn(key, payload, f"missing key {key!r}")

    def test_main_text_includes_dedup_label(self) -> None:
        out = StringIO()
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            code = cli.main(["--limit", "5"], out=out)
        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("effective_unique_records_count", rendered)

    def test_main_limit_caps_top_abs_sar(self) -> None:
        out = StringIO()
        with _patch_seams(
            payload=_make_payload(self.records), event_dates=self.event_dates,
        ):
            cli.main(["--json", "--limit", "1"], out=out)
        payload = json.loads(out.getvalue())
        self.assertLessEqual(len(payload["top_abs_sar"]), 1)


# ---------------------------------------------------------------------------
# Read-only contract — the dedup summary must never mutate the events.db
# the ``_load_event_dates`` seam reads from.
# ---------------------------------------------------------------------------


def _tmp_db_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_archive_stat_validation_dedup_summary_{uuid.uuid4().hex}.db",
    )


def _init_minimal_db(path: str) -> None:
    """Create a minimal events table the seam can SELECT against."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  headline TEXT,"
            "  event_date TEXT,"
            "  market_tickers TEXT,"
            "  mechanism_family TEXT"
            ")"
        )
        conn.executemany(
            "INSERT INTO events (headline, event_date, market_tickers, mechanism_family) "
            "VALUES (?, ?, ?, ?)",
            [
                ("Event 1", "2026-06-01", '[{"symbol":"AAPL"}]', "policy_constraint"),
                ("Event 2", "2026-06-02", '[{"symbol":"AAPL"}]', "policy_constraint"),
            ],
        )


def _snapshot_db(path: str) -> dict[str, list[tuple]]:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        snapshot: dict[str, list[tuple]] = {}
        for table in tables:
            rows = conn.execute(
                f"SELECT * FROM \"{table}\" ORDER BY rowid"
            ).fetchall()
            snapshot[table] = list(rows)
        return snapshot


class TestReadOnlyContract(unittest.TestCase):

    def test_load_event_dates_does_not_mutate_db(self) -> None:
        path = _tmp_db_path()
        try:
            _init_minimal_db(path)
            before = _snapshot_db(path)
            cli._load_event_dates(db_path=path, event_ids=[1, 2])
            after = _snapshot_db(path)
            self.assertEqual(
                before, after,
                "_load_event_dates must be strictly read-only",
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_summarize_dedup_does_not_mutate_db(self) -> None:
        # Patch _run_validation so we don't need a populated price_cache;
        # _load_event_dates runs against the real DB and is the only
        # surface that reads sqlite from the dedup summary.
        path = _tmp_db_path()
        try:
            _init_minimal_db(path)
            records = [
                _make_record(event_id=1, ticker="AAPL", horizon=1, p_value=0.1, fdr_q=0.1),
                _make_record(event_id=2, ticker="AAPL", horizon=1, p_value=0.1, fdr_q=0.1),
            ]
            payload = _make_payload(records)
            before = _snapshot_db(path)
            with patch.object(cli, "_run_validation", return_value=payload):
                cli.summarize_dedup(db_path=path, limit=5)
            after = _snapshot_db(path)
            self.assertEqual(
                before, after,
                "summarize_dedup must be strictly read-only end-to-end",
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
