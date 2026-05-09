"""Tests for ``scripts/archive_cleanup_execution_plan.py``.

Pin the read-only contract:

* The plan exposes the documented top-level shape:
  ``candidate_count``, ``batches``, ``risk_notes``,
  ``required_confirmation_flags``, ``recommended_next_action``.
* Each batch carries ``reason``, ``size``, ``event_ids``, ``examples``,
  ``manual_review_required_before_delete=True`` and ``description``.
* Batches are sorted alphabetically by reason key; only reasons with
  >= 1 flagged event produce a batch.
* Multi-reason events appear in every matching batch (so per-batch
  ``size`` totals may exceed ``candidate_count``).
* ``--limit`` truncates per-batch ``examples`` only — ``size`` and
  ``event_ids`` always reflect the full cluster.
* ``recommended_next_action`` is a closed two-string vocabulary.
* The patchable seam works two ways: a ``candidate_report=`` kwarg
  bypasses the upstream call entirely, and ``patch.object`` on
  ``plan._candidate_report.summarize_cleanup_candidates`` intercepts
  the underlying lookup.
* Read-only: repeated runs leave events byte-identical, only SELECT
  statements reach sqlite3, and the source pins forbid destructive
  SQL, paid seams, and filesystem destructors.
* CLI plumbing: ``--json``, ``--limit``, ``--db-path``,
  ``--fixture-timestamp-threshold``.
"""
from __future__ import annotations

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

from scripts import archive_cleanup_execution_plan as plan  # noqa: E402


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
    "batches",
    "risk_notes",
    "required_confirmation_flags",
    "recommended_next_action",
)


_BATCH_KEYS: tuple[str, ...] = (
    "reason",
    "size",
    "event_ids",
    "examples",
    "manual_review_required_before_delete",
    "description",
)


_REASON_KEYS: tuple[str, ...] = (
    "test_fixture_phrase",
    "rotating_macro_template",
    "fixture_timestamp_cluster",
    "duplicate_headline_event_date",
)


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
            f"test_acep_{uuid.uuid4().hex}.db",
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


class TestPlanShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_candidate_count_is_non_negative_int(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertIsInstance(result["candidate_count"], int)
        self.assertGreaterEqual(result["candidate_count"], 0)

    def test_batches_is_list(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertIsInstance(result["batches"], list)

    def test_risk_notes_is_non_empty_list_of_strings(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertIsInstance(result["risk_notes"], list)
        self.assertGreater(len(result["risk_notes"]), 0)
        for note in result["risk_notes"]:
            self.assertIsInstance(note, str)
            self.assertTrue(note.strip())

    def test_required_confirmation_flags_is_non_empty_list(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertIsInstance(result["required_confirmation_flags"], list)
        self.assertGreater(len(result["required_confirmation_flags"]), 0)
        for flag in result["required_confirmation_flags"]:
            self.assertIsInstance(flag, str)
            self.assertTrue(flag.strip())

    def test_recommended_next_action_is_closed_vocabulary(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertIn(
            result["recommended_next_action"],
            (plan._RECOMMENDED_OK, plan._RECOMMENDED_PLAN),
        )


# ---------------------------------------------------------------------------
# Empty / clean archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(_Base):
    def test_empty_archive_yields_no_batches(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["batches"], [])

    def test_empty_archive_recommends_ok(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], plan._RECOMMENDED_OK,
        )

    def test_empty_archive_still_carries_risk_notes_and_flags(self) -> None:
        # Stable shape: risk_notes and required_confirmation_flags
        # are present even on a clean archive so downstream consumers
        # always see the same fields.
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertGreater(len(result["risk_notes"]), 0)
        self.assertGreater(len(result["required_confirmation_flags"]), 0)


# ---------------------------------------------------------------------------
# Batch contract
# ---------------------------------------------------------------------------


class TestBatchContract(_Base):
    def test_each_batch_has_required_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertEqual(len(result["batches"]), 1)
        batch = result["batches"][0]
        for key in _BATCH_KEYS:
            self.assertIn(key, batch, f"missing batch key: {key}")

    def test_manual_review_flag_is_true_in_every_batch(self) -> None:
        # The user's spec: every batch must include explicit
        # ``manual_review_required_before_delete`` — this script never
        # auto-deletes.
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            _seed_event(conn, headline="Fed speakers rotate")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertGreater(len(result["batches"]), 0)
        for batch in result["batches"]:
            self.assertIs(
                batch["manual_review_required_before_delete"], True,
            )

    def test_batch_size_equals_event_ids_length(self) -> None:
        with self._conn() as conn:
            for _ in range(3):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        for batch in result["batches"]:
            self.assertEqual(batch["size"], len(batch["event_ids"]))

    def test_batches_sorted_by_reason_key(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            _seed_event(conn, headline="Fed speakers rotate")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        reasons_in_order = [b["reason"] for b in result["batches"]]
        self.assertEqual(reasons_in_order, sorted(reasons_in_order))

    def test_batch_reason_is_one_of_known_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        for batch in result["batches"]:
            self.assertIn(batch["reason"], _REASON_KEYS)

    def test_batch_description_is_non_empty_string(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        for batch in result["batches"]:
            self.assertIsInstance(batch["description"], str)
            self.assertTrue(batch["description"].strip())

    def test_event_ids_are_ints(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        for batch in result["batches"]:
            for eid in batch["event_ids"]:
                self.assertIsInstance(eid, int)


# ---------------------------------------------------------------------------
# Per-reason batching
# ---------------------------------------------------------------------------


class TestPerReasonBatching(_Base):
    def test_test_fixture_phrase_creates_batch(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        reasons = [b["reason"] for b in result["batches"]]
        self.assertIn("test_fixture_phrase", reasons)

    def test_rotating_macro_template_creates_batch(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Fed speakers rotate")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        reasons = [b["reason"] for b in result["batches"]]
        self.assertIn("rotating_macro_template", reasons)

    def test_fixture_timestamp_cluster_creates_batch(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="A",
                        timestamp="2026-05-08T06:11:11",
                        event_date="2026-05-08")
            _seed_event(conn, headline="B",
                        timestamp="2026-05-08T06:11:11",
                        event_date="2026-05-08")
            _seed_event(conn, headline="C",
                        timestamp="2026-05-08T06:11:11",
                        event_date="2026-05-08")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        reasons = [b["reason"] for b in result["batches"]]
        self.assertIn("fixture_timestamp_cluster", reasons)

    def test_duplicate_headline_event_date_creates_batch(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="OPEC announces 500kbpd cut",
                        timestamp="2026-04-15T09:00:00",
                        event_date="2026-04-15")
            _seed_event(conn, headline="OPEC announces 500kbpd cut",
                        timestamp="2026-04-15T11:00:00",
                        event_date="2026-04-15")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        reasons = [b["reason"] for b in result["batches"]]
        self.assertIn("duplicate_headline_event_date", reasons)

    def test_no_batch_for_reasons_with_zero_events(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        reasons = [b["reason"] for b in result["batches"]]
        self.assertEqual(reasons, ["test_fixture_phrase"])


# ---------------------------------------------------------------------------
# Multi-reason events span batches
# ---------------------------------------------------------------------------


class TestMultiReasonSpansBatches(_Base):
    def test_event_with_two_reasons_appears_in_two_batches(self) -> None:
        # ``Fed speakers rotate`` twice on the same event_date matches
        # rotating_macro_template AND duplicate_headline_event_date.
        with self._conn() as conn:
            id_a = _seed_event(conn, headline="Fed speakers rotate",
                               timestamp="2026-04-30T08:00:00",
                               event_date="2026-04-30")
            id_b = _seed_event(conn, headline="Fed speakers rotate",
                               timestamp="2026-04-30T09:00:00",
                               event_date="2026-04-30")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)

        ids_by_reason = {
            b["reason"]: set(b["event_ids"]) for b in result["batches"]
        }
        self.assertIn("rotating_macro_template", ids_by_reason)
        self.assertIn("duplicate_headline_event_date", ids_by_reason)
        self.assertIn(id_a, ids_by_reason["rotating_macro_template"])
        self.assertIn(id_a, ids_by_reason["duplicate_headline_event_date"])
        self.assertIn(id_b, ids_by_reason["rotating_macro_template"])
        self.assertIn(id_b, ids_by_reason["duplicate_headline_event_date"])

    def test_sum_of_batch_sizes_can_exceed_candidate_count(self) -> None:
        # An event matching N reasons appears in N batches; aggregate
        # ``size`` totals therefore satisfy
        # ``sum(batch.size) >= candidate_count``.
        with self._conn() as conn:
            _seed_event(conn, headline="Fed speakers rotate",
                        timestamp="2026-04-30T08:00:00",
                        event_date="2026-04-30")
            _seed_event(conn, headline="Fed speakers rotate",
                        timestamp="2026-04-30T09:00:00",
                        event_date="2026-04-30")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        total = sum(b["size"] for b in result["batches"])
        self.assertGreaterEqual(total, result["candidate_count"])


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimitTruncation(_Base):
    def test_limit_caps_examples_per_batch_but_not_event_ids(self) -> None:
        # Unique timestamps and event_dates so only test_fixture_phrase
        # fires -- exactly one batch, lets us assert per-batch caps
        # without aliasing across timestamp / duplicate clusters.
        with self._conn() as conn:
            for i in range(8):
                _seed_event(
                    conn,
                    headline="Macro shock test event",
                    timestamp=f"2026-04-01T{10 + i:02d}:00:00",
                    event_date=f"2026-04-{1 + i:02d}",
                )
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp, limit=3)
        self.assertEqual(len(result["batches"]), 1)
        batch = result["batches"][0]
        self.assertEqual(batch["reason"], "test_fixture_phrase")
        self.assertEqual(batch["size"], 8)
        self.assertEqual(len(batch["event_ids"]), 8)
        self.assertEqual(len(batch["examples"]), 3)

    def test_limit_zero_yields_empty_examples_with_intact_event_ids(self) -> None:
        with self._conn() as conn:
            for i in range(4):
                _seed_event(
                    conn,
                    headline="Macro shock test event",
                    timestamp=f"2026-04-01T{10 + i:02d}:00:00",
                    event_date=f"2026-04-{1 + i:02d}",
                )
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp, limit=0)
        self.assertEqual(len(result["batches"]), 1)
        batch = result["batches"][0]
        self.assertEqual(batch["examples"], [])
        self.assertEqual(len(batch["event_ids"]), 4)

    def test_negative_limit_clamped_to_zero(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp, limit=-7)
        self.assertEqual(result["batches"][0]["examples"], [])
        self.assertEqual(len(result["batches"][0]["event_ids"]), 1)


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


class TestPatchableSeam(unittest.TestCase):
    def test_candidate_report_kwarg_overrides_db_call(self) -> None:
        # Direct injection: passing a ``candidate_report=`` dict
        # bypasses summarize_cleanup_candidates entirely.
        injected = {
            "candidate_count": 3,
            "reasons": {
                "test_fixture_phrase": 3,
                "rotating_macro_template": 0,
                "fixture_timestamp_cluster": 0,
                "duplicate_headline_event_date": 0,
            },
            "examples": [
                {"event_id": 1, "headline": "x", "timestamp": "t",
                 "event_date": "d", "reasons": ["test_fixture_phrase"]},
                {"event_id": 2, "headline": "y", "timestamp": "t",
                 "event_date": "d", "reasons": ["test_fixture_phrase"]},
                {"event_id": 3, "headline": "z", "timestamp": "t",
                 "event_date": "d", "reasons": ["test_fixture_phrase"]},
            ],
            "fixture_timestamp_threshold": 3,
            "recommended_next_action": "anything",
        }
        result = plan.build_execution_plan(candidate_report=injected)
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(len(result["batches"]), 1)
        batch = result["batches"][0]
        self.assertEqual(batch["reason"], "test_fixture_phrase")
        self.assertEqual(batch["size"], 3)
        self.assertEqual(batch["event_ids"], [1, 2, 3])

    def test_module_attribute_patch_intercepts_underlying_call(self) -> None:
        # ``patch.object`` on the imported module attribute is the
        # canonical patchable seam.
        fake_report = {
            "candidate_count": 1,
            "reasons": {key: 0 for key in _REASON_KEYS},
            "examples": [
                {"event_id": 99, "headline": "fake",
                 "timestamp": "t", "event_date": "d",
                 "reasons": ["rotating_macro_template"]},
            ],
            "fixture_timestamp_threshold": 3,
            "recommended_next_action": "anything",
        }
        fake_report["reasons"]["rotating_macro_template"] = 1

        with patch.object(
            plan._candidate_report,
            "summarize_cleanup_candidates",
            return_value=fake_report,
        ):
            result = plan.build_execution_plan(db_path="/does/not/matter")

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(len(result["batches"]), 1)
        self.assertEqual(result["batches"][0]["reason"], "rotating_macro_template")
        self.assertEqual(result["batches"][0]["event_ids"], [99])

    def test_explicit_candidate_report_short_circuits_module_call(self) -> None:
        # When ``candidate_report=`` is supplied, the module-attribute
        # call must NOT fire — even if patched to raise.
        injected = {
            "candidate_count": 0,
            "reasons": {key: 0 for key in _REASON_KEYS},
            "examples": [],
            "fixture_timestamp_threshold": 3,
            "recommended_next_action": "anything",
        }

        def _explode(*_args, **_kwargs):  # pragma: no cover — must not run
            raise AssertionError(
                "summarize_cleanup_candidates was called despite explicit "
                "candidate_report kwarg"
            )

        with patch.object(
            plan._candidate_report,
            "summarize_cleanup_candidates",
            side_effect=_explode,
        ):
            result = plan.build_execution_plan(candidate_report=injected)

        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["batches"], [])


# ---------------------------------------------------------------------------
# Read-only contract
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
        plan.build_execution_plan(db_path=self._tmp)
        plan.build_execution_plan(db_path=self._tmp)
        plan.build_execution_plan(db_path=self._tmp)
        after = _snapshot_events(self._tmp)
        self.assertEqual(before, after)

    def test_only_select_statements_reach_sqlite(self) -> None:
        # End-to-end: while ``build_execution_plan`` runs, every SQL
        # statement that reaches sqlite3 must be a SELECT.  Catches a
        # future regression where the plan grows its own SQL.
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
            plan.build_execution_plan(db_path=self._tmp)

        self.assertGreater(
            len(statements), 0,
            "expected at least one SQL statement during the plan run",
        )
        for sql in statements:
            head = sql.lstrip().split(None, 1)[0].upper()
            self.assertEqual(
                head, "SELECT",
                f"non-SELECT statement issued during plan: {sql!r}",
            )

    def test_module_source_has_no_destructive_sql(self) -> None:
        # Defense-in-depth source pin: the module must contain no
        # destructive SQL syntax.  Patterns match real SQL (each
        # operator + its required follow-up token) so the docstring
        # narrative listing the forbidden operations does not trip
        # the check.
        src = Path(plan.__file__).read_text(encoding="utf-8")
        forbidden_sql = (
            r"\bDELETE\s+FROM\b",
            r"\bUPDATE\s+\w+\s+SET\b",
            r"\bINSERT\s+INTO\b",
            r"\bDROP\s+TABLE\b",
            r"\bTRUNCATE\s+TABLE\b",
            r"\bALTER\s+TABLE\b",
        )
        for pat in forbidden_sql:
            self.assertIsNone(
                re.search(pat, src, flags=re.IGNORECASE),
                f"forbidden destructive SQL {pat!r} in execution plan",
            )

    def test_module_source_does_not_import_paid_seams(self) -> None:
        src = Path(plan.__file__).read_text(encoding="utf-8")
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
                f"forbidden import pattern {pat!r} in execution plan",
            )

    def test_module_source_does_not_call_filesystem_destructors(self) -> None:
        # Patterns require an open paren so the docstring narrative
        # listing forbidden destructors (os.remove / os.unlink /
        # shutil.rmtree / Path.unlink) does not trip the check; only
        # actual call sites match.
        src = Path(plan.__file__).read_text(encoding="utf-8")
        for pat in (
            r"\bos\.remove\s*\(",
            r"\bos\.unlink\s*\(",
            r"\bshutil\.rmtree\s*\(",
            r"\.unlink\s*\(",
        ):
            self.assertIsNone(
                re.search(pat, src),
                f"filesystem destructor pattern {pat!r} in execution plan",
            )


# ---------------------------------------------------------------------------
# Recommended-next-action vocabulary
# ---------------------------------------------------------------------------


class TestRecommendedNextActionVocabulary(_Base):
    def test_zero_candidates_recommends_ok(self) -> None:
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], plan._RECOMMENDED_OK,
        )

    def test_any_candidate_recommends_plan(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = plan.build_execution_plan(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], plan._RECOMMENDED_PLAN,
        )

    def test_recommended_plan_explicitly_disclaims_writes(self) -> None:
        # The closed-vocabulary string must explicitly say this script
        # makes no DB writes — so an operator reading the JSON does
        # not assume the plan also performs the deletion.
        self.assertIn("no DB writes", plan._RECOMMENDED_PLAN)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCliPlumbing(_Base):
    def test_main_default_returns_zero_and_prints_text(self) -> None:
        out = StringIO()
        code = plan.main(["--db-path", self._tmp], out=out)
        self.assertEqual(code, 0)
        self.assertIn("execution plan", out.getvalue().lower())

    def test_main_json_emits_parseable_payload(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        out = StringIO()
        code = plan.main(["--db-path", self._tmp, "--json"], out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        for key in _TOP_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(len(payload["batches"]), 1)
        self.assertIs(
            payload["batches"][0]["manual_review_required_before_delete"],
            True,
        )

    def test_main_limit_truncates_batch_examples_only(self) -> None:
        with self._conn() as conn:
            for _ in range(5):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        out = StringIO()
        code = plan.main(
            ["--db-path", self._tmp, "--json", "--limit", "2"], out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["candidate_count"], 5)
        batch = payload["batches"][0]
        self.assertEqual(batch["size"], 5)
        self.assertEqual(len(batch["event_ids"]), 5)
        self.assertEqual(len(batch["examples"]), 2)

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
        code = plan.main(
            [
                "--db-path", self._tmp, "--json",
                "--fixture-timestamp-threshold", "2",
            ],
            out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        reasons = [b["reason"] for b in payload["batches"]]
        self.assertIn("fixture_timestamp_cluster", reasons)


# ---------------------------------------------------------------------------
# Live archive sanity — opt-in
# ---------------------------------------------------------------------------


class TestLiveArchiveSanity(unittest.TestCase):
    """If the project's ``events.db`` is present, the plan must run
    against it without raising and produce a well-formed report.
    Skipped when the DB file is absent so CI stays portable.
    """

    def setUp(self) -> None:
        self._project_root = Path(__file__).resolve().parents[1]
        self._db = self._project_root / "events.db"
        if not self._db.exists():
            self.skipTest(f"no live archive at {self._db}")

    def test_live_archive_produces_well_formed_plan(self) -> None:
        result = plan.build_execution_plan(db_path=str(self._db))
        for key in _TOP_KEYS:
            self.assertIn(key, result)
        for batch in result["batches"]:
            for key in _BATCH_KEYS:
                self.assertIn(key, batch)
            self.assertIs(
                batch["manual_review_required_before_delete"], True,
            )
            self.assertIn(batch["reason"], _REASON_KEYS)


if __name__ == "__main__":
    unittest.main()
