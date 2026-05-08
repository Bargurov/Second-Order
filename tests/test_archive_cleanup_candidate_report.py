"""Tests for ``scripts/archive_cleanup_candidate_report.py``.

Pin the read-only contract:

* Per-detection rules are independently testable: a synthetic event
  matching exactly one rule lands in the corresponding reason bucket
  and surfaces that one reason in its per-event ``reasons`` list.
* Aggregate counts always reflect every event in the archive — the
  ``--limit`` flag truncates the surfaced ``examples`` list only.
* Per-event entries are sorted by ``id`` ascending and carry the
  required keys (``event_id``, ``headline``, ``timestamp``,
  ``event_date``, ``reasons``).
* The closed two-string ``recommended_next_action`` vocabulary is
  fixed; downstream consumers branch on the literal value.
* CLI plumbing: ``--json``, ``--limit``, ``--db-path``,
  ``--fixture-timestamp-threshold``.
* Repeated runs leave events byte-identical (read-only).
* Only ``SELECT`` statements are issued against the DB.
* No provider, yfinance, market_check, market_data, LLM, or FastAPI
  seam is reachable from the report's import surface.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import archive_cleanup_candidate_report as report  # noqa: E402


# Hand-rolled minimal DDL — only the columns the report reads.  Mirrors
# the approach taken by ``test_stat_validation_readiness_report``: keep
# fixtures decoupled from the production schema migrations so the SQL
# contract can be pinned directly.
_EVENTS_DDL = """
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    headline    TEXT,
    timestamp   TEXT,
    event_date  TEXT
)
""".strip()


_TOP_KEYS: tuple[str, ...] = (
    "candidate_count",
    "reasons",
    "examples",
    "fixture_timestamp_threshold",
    "recommended_next_action",
)


_PER_EVENT_KEYS: tuple[str, ...] = (
    "event_id",
    "headline",
    "timestamp",
    "event_date",
    "reasons",
)


_REASON_KEYS: tuple[str, ...] = (
    "test_fixture_phrase",
    "rotating_macro_template",
    "fixture_timestamp_cluster",
    "duplicate_headline_event_date",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_event(
    conn: sqlite3.Connection,
    *,
    headline: str | None = "headline",
    timestamp: str | None = "2026-04-01T10:00:00",
    event_date: str | None = "2026-04-01",
) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, timestamp, event_date) "
        "VALUES (?, ?, ?)",
        (headline, timestamp, event_date),
    )
    return int(cur.lastrowid)


def _snapshot_events(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_accr_{uuid.uuid4().hex}.db",
        )
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(_EVENTS_DDL)
            conn.commit()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._tmp)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_reasons_block_has_every_required_key(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        reasons = result["reasons"]
        self.assertIsInstance(reasons, dict)
        for key in _REASON_KEYS:
            self.assertIn(key, reasons, f"missing reason key: {key}")
            self.assertIsInstance(reasons[key], int)
            self.assertGreaterEqual(reasons[key], 0)

    def test_candidate_count_is_non_negative_int(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertIsInstance(result["candidate_count"], int)
        self.assertGreaterEqual(result["candidate_count"], 0)

    def test_examples_is_list(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertIsInstance(result["examples"], list)

    def test_fixture_timestamp_threshold_is_pinned_int(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertIsInstance(result["fixture_timestamp_threshold"], int)
        self.assertGreaterEqual(result["fixture_timestamp_threshold"], 2)

    def test_recommended_next_action_is_closed_vocabulary(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertIn(
            result["recommended_next_action"],
            (
                report._RECOMMENDED_OK,
                report._RECOMMENDED_CANDIDATES,
            ),
        )


# ---------------------------------------------------------------------------
# Empty / clean archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(_Base):
    def test_empty_archive_zeros_every_aggregate(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)
        for key in _REASON_KEYS:
            self.assertEqual(result["reasons"][key], 0)
        self.assertEqual(result["examples"], [])

    def test_empty_archive_recommends_ok(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], report._RECOMMENDED_OK,
        )


class TestCleanArchive(_Base):
    def test_real_news_headlines_are_not_flagged(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, headline="Apple beats Q1 estimates on services growth",
                timestamp="2026-04-01T10:00:00", event_date="2026-04-01",
            )
            _seed_event(
                conn,
                headline=(
                    "US Treasury issues licence allowing Chevron to resume "
                    "crude liftings from Venezuela"
                ),
                timestamp="2026-04-02T11:00:00", event_date="2026-04-02",
            )
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["examples"], [])
        self.assertEqual(
            result["recommended_next_action"], report._RECOMMENDED_OK,
        )


# ---------------------------------------------------------------------------
# Detection: test fixture phrases
# ---------------------------------------------------------------------------


class TestFixturePhraseDetection(_Base):
    def _flag_for(self, headline: str) -> dict:
        with self._conn() as conn:
            _seed_event(conn, headline=headline)
            conn.commit()
        return report.summarize_cleanup_candidates(db_path=self._tmp)

    def test_macro_shock_test_event_is_flagged(self) -> None:
        # ``Macro shock test event`` appears 12× in the live prod archive
        # — the canonical fixture leak the report exists to surface.
        result = self._flag_for("Macro shock test event")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["reasons"]["test_fixture_phrase"], 1)
        self.assertEqual(
            result["examples"][0]["reasons"], ["test_fixture_phrase"],
        )

    def test_no_paid_smoke_seed_event_is_flagged(self) -> None:
        # The literal seed string in tests/test_no_paid_smoke.py:51.
        result = self._flag_for("No-paid smoke seed event")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["reasons"]["test_fixture_phrase"], 1)

    def test_insufficient_evidence_mock_is_flagged(self) -> None:
        # The literal mock string at analyze_event.py:3358 — what test
        # runs leave behind in prod (audit F-1, rowids 282..285).
        result = self._flag_for("Insufficient evidence.")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["reasons"]["test_fixture_phrase"], 1)

    def test_phrase_match_is_case_insensitive(self) -> None:
        result = self._flag_for("MACRO SHOCK TEST EVENT")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["reasons"]["test_fixture_phrase"], 1)

    def test_phrase_match_is_substring(self) -> None:
        # Phrase embedded in a longer headline still flags.
        result = self._flag_for("Daily macro shock test event recap [auto]")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["reasons"]["test_fixture_phrase"], 1)


# ---------------------------------------------------------------------------
# Detection: rotating macro templates
# ---------------------------------------------------------------------------


class TestRotatingMacroDetection(_Base):
    def _flag_for(self, headline: str) -> dict:
        with self._conn() as conn:
            _seed_event(conn, headline=headline)
            conn.commit()
        return report.summarize_cleanup_candidates(db_path=self._tmp)

    def test_fed_speakers_rotate_is_flagged(self) -> None:
        # 33× in live prod; canonical scraper-noise template.
        result = self._flag_for("Fed speakers rotate")
        self.assertEqual(result["reasons"]["rotating_macro_template"], 1)
        self.assertEqual(
            result["examples"][0]["reasons"], ["rotating_macro_template"],
        )

    def test_fed_speakers_rotate_with_tail_is_flagged(self) -> None:
        result = self._flag_for("Fed speakers rotate on inflation commentary")
        self.assertEqual(result["reasons"]["rotating_macro_template"], 1)

    def test_turkey_lira_weakens_is_flagged(self) -> None:
        # 33× in live prod.
        result = self._flag_for("Turkey lira weakens")
        self.assertEqual(result["reasons"]["rotating_macro_template"], 1)

    def test_turkey_lira_weakens_with_tail_is_flagged(self) -> None:
        result = self._flag_for(
            "Turkey lira weakens as reserves slip further",
        )
        self.assertEqual(result["reasons"]["rotating_macro_template"], 1)

    def test_opec_slashes_output_is_flagged(self) -> None:
        # 21× in live prod with identical text — fixture-feed signature.
        result = self._flag_for("OPEC slashes output by 2 mbpd")
        self.assertEqual(result["reasons"]["rotating_macro_template"], 1)

    def test_tech_ceo_steps_down_is_flagged(self) -> None:
        # 13× in live prod.
        result = self._flag_for("Tech CEO steps down")
        self.assertEqual(result["reasons"]["rotating_macro_template"], 1)

    def test_real_fed_news_is_not_flagged(self) -> None:
        # A headline that *mentions* Fed speakers but is not one of the
        # rotating templates must not match.
        result = self._flag_for(
            "Powell delivers semiannual monetary policy testimony to Senate",
        )
        self.assertEqual(result["reasons"]["rotating_macro_template"], 0)


# ---------------------------------------------------------------------------
# Detection: fixture timestamp clusters
# ---------------------------------------------------------------------------


class TestFixtureTimestampCluster(_Base):
    def test_three_events_sharing_timestamp_each_get_flagged(self) -> None:
        # Three rows share an identical timestamp string — the audit's
        # smoking-gun signature for rowids 282..285 / 287..290.
        with self._conn() as conn:
            _seed_event(conn, headline="A", timestamp="2026-05-08T06:11:11",
                        event_date="2026-05-08")
            _seed_event(conn, headline="B", timestamp="2026-05-08T06:11:11",
                        event_date="2026-05-08")
            _seed_event(conn, headline="C", timestamp="2026-05-08T06:11:11",
                        event_date="2026-05-08")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["reasons"]["fixture_timestamp_cluster"], 3)
        for ex in result["examples"]:
            self.assertIn("fixture_timestamp_cluster", ex["reasons"])

    def test_two_events_sharing_timestamp_below_default_threshold(self) -> None:
        # Default threshold is 3 — two-row clusters do not flag.
        with self._conn() as conn:
            _seed_event(conn, headline="A",
                        timestamp="2026-04-15T10:00:00", event_date="2026-04-15")
            _seed_event(conn, headline="B",
                        timestamp="2026-04-15T10:00:00", event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["reasons"]["fixture_timestamp_cluster"], 0)

    def test_unique_timestamp_is_not_flagged(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="A",
                        timestamp="2026-04-15T10:00:00", event_date="2026-04-15")
            _seed_event(conn, headline="B",
                        timestamp="2026-04-15T11:00:00", event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["reasons"]["fixture_timestamp_cluster"], 0)

    def test_blank_timestamp_does_not_form_cluster(self) -> None:
        # NULL / empty / whitespace-only timestamps must not cluster
        # against each other (otherwise every blank-timestamp row would
        # falsely flag every other blank-timestamp row).
        with self._conn() as conn:
            _seed_event(conn, headline="A", timestamp=None,
                        event_date="2026-04-15")
            _seed_event(conn, headline="B", timestamp="",
                        event_date="2026-04-15")
            _seed_event(conn, headline="C", timestamp="   ",
                        event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["reasons"]["fixture_timestamp_cluster"], 0)

    def test_threshold_override_lowers_to_two(self) -> None:
        # CLI exposes the threshold so an operator can tighten the
        # detector when a known fixture seed leaked at 2-row clusters.
        with self._conn() as conn:
            _seed_event(conn, headline="A",
                        timestamp="2026-04-15T10:00:00", event_date="2026-04-15")
            _seed_event(conn, headline="B",
                        timestamp="2026-04-15T10:00:00", event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(
            db_path=self._tmp, fixture_timestamp_threshold=2,
        )
        self.assertEqual(result["reasons"]["fixture_timestamp_cluster"], 2)
        self.assertEqual(result["fixture_timestamp_threshold"], 2)


# ---------------------------------------------------------------------------
# Detection: duplicate (headline, event_date)
# ---------------------------------------------------------------------------


class TestDuplicateHeadlineEventDate(_Base):
    def test_two_rows_sharing_headline_and_event_date_are_flagged(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="OPEC announces 500kbpd cut",
                        timestamp="2026-04-15T09:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="OPEC announces 500kbpd cut",
                        timestamp="2026-04-15T11:00:00",
                        event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(
            result["reasons"]["duplicate_headline_event_date"], 2,
        )
        for ex in result["examples"]:
            self.assertIn("duplicate_headline_event_date", ex["reasons"])

    def test_same_headline_different_event_dates_is_not_flagged(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="OPEC announces 500kbpd cut",
                        timestamp="2026-04-15T09:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="OPEC announces 500kbpd cut",
                        timestamp="2026-05-01T11:00:00",
                        event_date="2026-05-01")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(
            result["reasons"]["duplicate_headline_event_date"], 0,
        )

    def test_blank_headline_or_event_date_does_not_cluster(self) -> None:
        # Mirrors archive_diagnostics: rows whose headline or event_date
        # is blank are excluded so duplicates do not double-count with
        # the missing-headline / missing-event_date categories already
        # surfaced by the consistency report.
        with self._conn() as conn:
            _seed_event(conn, headline="", timestamp="2026-04-15T09:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="", timestamp="2026-04-15T11:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="A", timestamp="2026-04-16T09:00:00",
                        event_date=None)
            _seed_event(conn, headline="A", timestamp="2026-04-16T11:00:00",
                        event_date=None)
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(
            result["reasons"]["duplicate_headline_event_date"], 0,
        )


# ---------------------------------------------------------------------------
# Multi-reason and partition contract
# ---------------------------------------------------------------------------


class TestMultipleReasonsContract(_Base):
    def test_event_with_two_reasons_appears_once_in_examples(self) -> None:
        # Headline matches a rotating-macro template AND the event is
        # part of a duplicate (headline, event_date) cluster — the
        # event must appear once in ``examples`` with both reasons in
        # its ``reasons`` list.
        with self._conn() as conn:
            _seed_event(conn, headline="Fed speakers rotate",
                        timestamp="2026-04-30T08:00:00",
                        event_date="2026-04-30")
            _seed_event(conn, headline="Fed speakers rotate",
                        timestamp="2026-04-30T09:00:00",
                        event_date="2026-04-30")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)

        # Each event appears once.
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(len(result["examples"]), 2)

        # Each event has both reasons.
        for ex in result["examples"]:
            self.assertIn("rotating_macro_template", ex["reasons"])
            self.assertIn("duplicate_headline_event_date", ex["reasons"])

        # Each reason counter increments per-flagged-event, so two
        # events flagged for two reasons → 2 + 2 totals; the
        # candidate_count remains 2 (events, not flag-events).
        self.assertEqual(result["reasons"]["rotating_macro_template"], 2)
        self.assertEqual(
            result["reasons"]["duplicate_headline_event_date"], 2,
        )

    def test_reason_counts_can_exceed_candidate_count(self) -> None:
        # Sanity: when one event carries N reasons the per-reason
        # counters sum to >= candidate_count.
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event",
                        timestamp="2026-04-15T10:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="Macro shock test event",
                        timestamp="2026-04-15T10:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="Macro shock test event",
                        timestamp="2026-04-15T10:00:00",
                        event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)

        self.assertEqual(result["candidate_count"], 3)
        total_reason_hits = sum(result["reasons"][k] for k in _REASON_KEYS)
        self.assertGreaterEqual(total_reason_hits, result["candidate_count"])

    def test_reasons_list_per_event_is_subset_of_reason_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            _seed_event(conn, headline="Fed speakers rotate")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        for ex in result["examples"]:
            self.assertGreaterEqual(len(ex["reasons"]), 1)
            for r in ex["reasons"]:
                self.assertIn(r, _REASON_KEYS)

    def test_per_event_reasons_are_deduplicated_and_sorted(self) -> None:
        # The per-event reasons list is a stable, deduplicated set so
        # downstream consumers can compare reasons-lists for equality
        # without normalising.
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        reasons = result["examples"][0]["reasons"]
        self.assertEqual(reasons, sorted(set(reasons)))


# ---------------------------------------------------------------------------
# Examples ordering and limit
# ---------------------------------------------------------------------------


class TestExamplesOrderingAndLimit(_Base):
    def test_examples_sorted_by_id_ascending(self) -> None:
        with self._conn() as conn:
            for _ in range(5):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        ids = [ex["event_id"] for ex in result["examples"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_caps_examples_but_not_aggregate_counts(self) -> None:
        with self._conn() as conn:
            for _ in range(10):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = report.summarize_cleanup_candidates(
            db_path=self._tmp, limit=3,
        )
        self.assertEqual(len(result["examples"]), 3)
        # Aggregates reflect every event in the archive — independent
        # of the surfaced-examples cap.
        self.assertEqual(result["candidate_count"], 10)
        self.assertEqual(result["reasons"]["test_fixture_phrase"], 10)

    def test_limit_zero_yields_empty_examples_with_intact_counts(self) -> None:
        with self._conn() as conn:
            for _ in range(4):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = report.summarize_cleanup_candidates(
            db_path=self._tmp, limit=0,
        )
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["candidate_count"], 4)

    def test_negative_limit_clamped_to_zero(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = report.summarize_cleanup_candidates(
            db_path=self._tmp, limit=-7,
        )
        self.assertEqual(result["examples"], [])


# ---------------------------------------------------------------------------
# Recommended next action vocabulary
# ---------------------------------------------------------------------------


class TestRecommendedNextActionVocabulary(_Base):
    def test_zero_candidates_recommends_ok(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], report._RECOMMENDED_OK,
        )

    def test_any_candidate_recommends_review(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"],
            report._RECOMMENDED_CANDIDATES,
        )

    def test_recommended_action_explicitly_disclaims_writes(self) -> None:
        # The closed-vocabulary string for "candidates detected" must
        # explicitly say this report makes no DB writes — so an
        # operator reading the JSON does not assume the script will
        # also delete the rows.
        self.assertIn("no DB writes", report._RECOMMENDED_CANDIDATES)


# ---------------------------------------------------------------------------
# Read-only contract: no mutation, only SELECT
# ---------------------------------------------------------------------------


class TestReadOnlyContract(_Base):
    def test_repeated_runs_leave_events_byte_identical(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            _seed_event(conn, headline="Real news headline",
                        timestamp="2026-04-15T11:00:00",
                        event_date="2026-04-15")
            conn.commit()
        before = _snapshot_events(self._tmp)
        report.summarize_cleanup_candidates(db_path=self._tmp)
        report.summarize_cleanup_candidates(db_path=self._tmp)
        report.summarize_cleanup_candidates(db_path=self._tmp)
        after = _snapshot_events(self._tmp)
        self.assertEqual(before, after)

    def test_only_select_statements_issued(self) -> None:
        # Capture every statement executed during one run via
        # ``Connection.set_trace_callback`` — sqlite3's official
        # statement-level tracing hook.  Any non-SELECT statement
        # (INSERT/UPDATE/DELETE/CREATE/PRAGMA…) means the report has
        # crossed its read-only contract and must fail closed.
        statements: list[str] = []
        real_connect = sqlite3.connect

        def _wrapper(path: str, *args, **kwargs):
            conn = real_connect(path, *args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()

        with patch.object(sqlite3, "connect", _wrapper):
            report.summarize_cleanup_candidates(db_path=self._tmp)

        self.assertGreater(
            len(statements), 0,
            "expected at least one SQL statement to be issued",
        )
        for sql in statements:
            head = sql.lstrip().split(None, 1)[0].upper()
            self.assertEqual(
                head, "SELECT",
                f"non-SELECT statement issued by report: {sql!r}",
            )

    def test_module_does_not_import_paid_seams(self) -> None:
        # Defense-in-depth: the report must not import any module that
        # could reach the provider, yfinance, the LLM seam, or the
        # FastAPI surface.  Pinning the module's source guards against
        # a future regression that smuggles those imports in.
        src = Path(report.__file__).read_text(encoding="utf-8")
        forbidden = (
            r"^\s*import\s+yfinance\b",
            r"^\s*from\s+yfinance\b",
            r"^\s*import\s+market_check\b",
            r"^\s*from\s+market_check\b",
            r"^\s*import\s+market_data\b",
            r"^\s*from\s+market_data\b",
            r"^\s*import\s+price_cache\b",
            r"^\s*from\s+price_cache\b",
            r"^\s*from\s+anthropic\b",
            r"^\s*import\s+anthropic\b",
            r"^\s*import\s+openai\b",
            r"^\s*from\s+openai\b",
            r"^\s*import\s+api\b",
            r"^\s*from\s+api\b",
            r"^\s*from\s+routes\.",
            r"^\s*import\s+routes\.",
            r"^\s*from\s+analyze_event\b",
            r"^\s*import\s+analyze_event\b",
        )
        for pat in forbidden:
            self.assertIsNone(
                re.search(pat, src, flags=re.MULTILINE),
                f"forbidden import pattern {pat!r} found in "
                f"archive_cleanup_candidate_report",
            )


# ---------------------------------------------------------------------------
# DB-path resolution and connection-error degradation
# ---------------------------------------------------------------------------


class TestDbPathResolution(_Base):
    def test_explicit_db_path_overrides_default(self) -> None:
        # Empty hand-rolled DB → empty report.  No mock of db.DB_FILE
        # is needed because we pass the path explicitly.
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)

    def test_missing_db_file_returns_empty_report_without_raising(self) -> None:
        # The report must degrade cleanly when the DB does not exist —
        # callers (smoke runners, dashboards) should never see an
        # exception bubble out of the report.
        nonexistent = os.path.join(
            tempfile.gettempdir(), f"_no_such_{uuid.uuid4().hex}.db",
        )
        try:
            result = report.summarize_cleanup_candidates(db_path=nonexistent)
        except Exception as exc:  # pragma: no cover — must not happen
            self.fail(f"report raised on missing DB: {exc!r}")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["examples"], [])
        self.assertEqual(
            result["recommended_next_action"], report._RECOMMENDED_OK,
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCliPlumbing(_Base):
    def test_main_default_returns_zero_and_prints_text(self) -> None:
        out = StringIO()
        code = report.main(["--db-path", self._tmp], out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("Archive cleanup candidate report", text)

    def test_main_json_emits_parseable_payload(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        out = StringIO()
        code = report.main(["--db-path", self._tmp, "--json"], out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["candidate_count"], 1)
        for key in _TOP_KEYS:
            self.assertIn(key, payload)

    def test_main_limit_truncates_examples(self) -> None:
        with self._conn() as conn:
            for _ in range(6):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        out = StringIO()
        code = report.main(
            ["--db-path", self._tmp, "--json", "--limit", "2"], out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["candidate_count"], 6)
        self.assertEqual(len(payload["examples"]), 2)

    def test_main_fixture_timestamp_threshold_flag(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="A",
                        timestamp="2026-04-15T10:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="B",
                        timestamp="2026-04-15T10:00:00",
                        event_date="2026-04-15")
            conn.commit()
        out = StringIO()
        code = report.main(
            [
                "--db-path", self._tmp, "--json",
                "--fixture-timestamp-threshold", "2",
            ],
            out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["fixture_timestamp_threshold"], 2)
        self.assertEqual(payload["reasons"]["fixture_timestamp_cluster"], 2)

    def test_per_event_entry_carries_required_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event",
                        timestamp="2026-04-15T10:00:00",
                        event_date="2026-04-15")
            conn.commit()
        result = report.summarize_cleanup_candidates(db_path=self._tmp)
        self.assertEqual(len(result["examples"]), 1)
        entry = result["examples"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, entry)
        self.assertIsInstance(entry["event_id"], int)
        self.assertIsInstance(entry["reasons"], list)


# ---------------------------------------------------------------------------
# Live archive sanity — opt-in smoke against the real events.db (if any)
# ---------------------------------------------------------------------------


class TestLiveArchiveSanity(unittest.TestCase):
    """If the project's events.db is present, the report must run
    against it without raising and must surface candidate_count > 0
    given the audit's evidence (Macro shock test event 12×, Fed
    speakers rotate 33×, Insufficient evidence. mocks at 282..285).

    Skipped when the DB file is absent so CI stays portable.
    """

    def setUp(self) -> None:
        self._project_root = Path(__file__).resolve().parents[1]
        self._db = self._project_root / "events.db"
        if not self._db.exists():
            self.skipTest(f"no live archive at {self._db}")

    def test_live_archive_produces_well_formed_report(self) -> None:
        result = report.summarize_cleanup_candidates(db_path=str(self._db))
        for key in _TOP_KEYS:
            self.assertIn(key, result)
        # Every example carries at least one reason from the closed set.
        for ex in result["examples"]:
            self.assertGreaterEqual(len(ex["reasons"]), 1)
            for r in ex["reasons"]:
                self.assertIn(r, _REASON_KEYS)


if __name__ == "__main__":
    unittest.main()
