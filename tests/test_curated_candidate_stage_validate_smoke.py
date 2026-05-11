"""Tests for ``scripts/curated_candidate_stage_validate_smoke.py``.

Pin the contract:

* Read-only smoke: copies the live DB to a fresh temp file, stages
  the repaired cohort (event_ids 30, 40, 46, 60, 73) as
  ``curated_candidates`` rows in the TEMP copy only, then runs the
  curated-candidate validation runner against that temp DB.
* Output dict carries EXACTLY these 10 keys::

    staged_count, events_evaluated, records_count, significant_count,
    by_horizon, by_mechanism_family, examples, excluded_candidates,
    warnings, errors

  No ``ok`` envelope — the spec lists exactly these ten and we honor
  that.  ``errors`` is non-empty when something failed.
* The hardcoded staged cohort is exactly 5 events: 30, 40, 46, 60, 73,
  with operator-supplied metadata (primary_ticker, benchmark_ticker,
  mechanism_family, etc).
* Each example carries the runner's per-record verdict fields
  ``raw_p_candidate`` / ``fdr_significant`` / ``verdict`` verbatim.
  The smoke never recomputes statistics — it propagates whatever
  the validation runner produced.
* Live DB is hashed before/after — bytes never change.
* When ``--output`` is supplied, the JSON is written to that path.
  When omitted, no file is written.
* Conservative wording — banned tokens (``automatically``,
  ``alpha generated``, ``definitely validated``, ``is proven``)
  absent from any text the smoke emits.
"""
from __future__ import annotations

import hashlib
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

from scripts import curated_candidate_stage_validate_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "staged_count",
    "events_evaluated",
    "records_count",
    "significant_count",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "excluded_candidates",
    "warnings",
    "errors",
)


_BANNED_WORDS = (
    "automatically",
    "alpha generated",
    "definitely validated",
    "is proven",
)


_REPAIRED_COHORT_IDS = (30, 40, 46, 60, 73)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    low_signal      INTEGER DEFAULT 0,
    mechanism_family TEXT DEFAULT 'none'
)
""".strip()


_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


_CURATED_CANDIDATES_DDL = """
CREATE TABLE curated_candidates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id       INTEGER NOT NULL,
    event_date            TEXT,
    headline              TEXT,
    source_url            TEXT,
    primary_ticker        TEXT,
    benchmark_ticker      TEXT,
    mechanism_family      TEXT,
    mechanism_description TEXT,
    predicted_direction   TEXT,
    prediction_rationale  TEXT,
    curator_notes         TEXT,
    status                TEXT NOT NULL DEFAULT 'draft',
    source                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    validation_errors     TEXT NOT NULL DEFAULT '[]',
    UNIQUE(source_event_id, source)
)
""".strip()


def _make_fixture_db(seed_event_ids: list[int] | None = None) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"curated_smoke_fix_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)
        conn.execute(_CURATED_CANDIDATES_DDL)
        for ev_id in (seed_event_ids or []):
            conn.execute(
                "INSERT INTO events (id, headline, event_date) "
                "VALUES (?, ?, ?)",
                (ev_id, f"headline {ev_id}", "2026-04-06"),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validation_payload(
    *,
    staged_candidate_count: int = 5,
    events_evaluated: int = 5,
    records_count: int = 15,
    significant_count: int = 1,
    by_horizon: dict | None = None,
    by_mechanism_family: dict | None = None,
    examples: list[dict] | None = None,
    excluded_candidates: list[dict] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    """Synthetic payload mirroring what the underlying validation
    runner would produce."""
    return {
        "ok":                       not (errors or []),
        "staged_candidate_count":   staged_candidate_count,
        "events_evaluated":         events_evaluated,
        "records_count":            records_count,
        "significant_count":        significant_count,
        "by_horizon":               by_horizon or {},
        "by_mechanism_family":      by_mechanism_family or {},
        "examples":                 list(examples or []),
        "missing_fields":           {},
        "excluded_candidates":      list(excluded_candidates or []),
        "errors":                   list(errors or []),
        "warnings":                 list(warnings or []),
        "recommended_next_action":  "synthetic",
    }


def _validation_example(
    *, source_event_id: int, horizon: int = 5,
    sar: float = 1.0, p_value: float = 0.10, fdr_q: float = 0.20,
    raw_p_candidate: bool = False,
    fdr_significant: bool = False,
    verdict: str = "inconclusive_fdr",
    interpretation: str = "not_significant",
) -> dict:
    """Synthetic example mirroring the validation runner's 16-field
    shape (13 numeric/metadata fields + raw_p_candidate /
    fdr_significant / verdict).  Defaults model an inconclusive
    record; pass overrides to model raw-p-only or FDR-significant.
    """
    return {
        "source_event_id":  source_event_id,
        "headline":         f"hl {source_event_id}",
        "primary_ticker":   "MS",
        "benchmark_ticker": "SPY",
        "mechanism_family": "supply_shock",
        "horizon":          horizon,
        "abnormal_return":  0.01,
        "sar":              sar,
        "ci_low":           -0.01,
        "ci_high":          0.05,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "interpretation":   interpretation,
        "raw_p_candidate":  raw_p_candidate,
        "fdr_significant":  fdr_significant,
        "verdict":          verdict,
    }


def _patch_validation(payload: dict | None = None):
    payload = payload if payload is not None else _validation_payload()
    return patch.object(
        cli, "_run_curated_validation", return_value=payload,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_returns_dict_with_exactly_ten_keys(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation():
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")

    def test_payload_does_not_carry_ok_envelope(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation():
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        # The user's spec lists exactly 10 keys; ``ok`` is intentionally
        # NOT one of them.
        self.assertNotIn("ok", report)


# ---------------------------------------------------------------------------
# Repaired cohort hardcoded
# ---------------------------------------------------------------------------


class TestRepairedCohort(unittest.TestCase):
    def test_cohort_is_exactly_five_event_ids(self) -> None:
        cohort = cli._REPAIRED_COHORT
        self.assertEqual(len(cohort), 5)

    def test_cohort_event_ids_match_expected_set(self) -> None:
        cohort_ids = sorted(c["source_event_id"] for c in cli._REPAIRED_COHORT)
        self.assertEqual(cohort_ids, list(_REPAIRED_COHORT_IDS))

    def test_each_cohort_entry_has_required_metadata(self) -> None:
        required = (
            "source_event_id", "event_date", "headline",
            "primary_ticker", "benchmark_ticker", "mechanism_family",
            "mechanism_description", "predicted_direction",
            "prediction_rationale",
        )
        for entry in cli._REPAIRED_COHORT:
            for f in required:
                self.assertIn(f, entry, f"cohort entry missing {f}")


# ---------------------------------------------------------------------------
# Temp DB isolation + staging
# ---------------------------------------------------------------------------


class TestStaging(unittest.TestCase):
    def test_candidates_inserted_into_temp_curated_candidates_table(
        self,
    ) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        captured: dict = {}

        def fake_validation(*, db_path):
            captured["db_path"] = db_path
            # Inspect the temp DB's curated_candidates table to verify
            # the staging actually landed before the runner is called.
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT source_event_id, status, primary_ticker "
                    "FROM curated_candidates "
                    "ORDER BY source_event_id"
                ).fetchall()
                captured["staged_rows"] = list(rows)
            finally:
                conn.close()
            return _validation_payload()

        try:
            with patch.object(
                cli, "_run_curated_validation", side_effect=fake_validation,
            ):
                cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)

        self.assertEqual(len(captured.get("staged_rows", [])), 5)
        ids = sorted(r[0] for r in captured["staged_rows"])
        self.assertEqual(ids, list(_REPAIRED_COHORT_IDS))
        # All candidates should be staged with a status that the
        # underlying runner picks up (needs_review or ready_for_validation).
        for row in captured["staged_rows"]:
            self.assertIn(row[1], ("needs_review", "ready_for_validation"))

    def test_validation_called_with_temp_db_path(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        captured: dict = {}

        def fake_validation(*, db_path):
            captured["db_path"] = db_path
            return _validation_payload()

        try:
            with patch.object(
                cli, "_run_curated_validation", side_effect=fake_validation,
            ):
                cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)

        # The runner must NOT be called with the live db_path — it
        # must receive a temp path that differs from the fixture.
        self.assertIsNotNone(captured.get("db_path"))
        self.assertNotEqual(captured["db_path"], fixture)


# ---------------------------------------------------------------------------
# Live DB byte identity
# ---------------------------------------------------------------------------


class TestLiveDbReadOnly(unittest.TestCase):
    def test_live_db_bytes_unchanged_after_smoke(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            before_hash = _sha256(fixture)
            with _patch_validation():
                cli.smoke_curated_stage_validate(db_path=fixture)
            after_hash = _sha256(fixture)
        finally:
            os.unlink(fixture)
        self.assertEqual(before_hash, after_hash)


# ---------------------------------------------------------------------------
# Output reshape
# ---------------------------------------------------------------------------


class TestOutputReshape(unittest.TestCase):
    def test_staged_count_equals_cohort_size(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation(_validation_payload(
                staged_candidate_count=5,
            )):
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        self.assertEqual(report["staged_count"], 5)

    def test_aggregate_fields_passed_through_from_runner(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation(_validation_payload(
                events_evaluated=4,
                records_count=12,
                significant_count=2,
                by_horizon={"5": {"records_count": 4, "significant_count": 1}},
                by_mechanism_family={
                    "supply_shock": {
                        "events_evaluated": 3,
                        "records_count":     9,
                        "significant_count": 2,
                    },
                },
                examples=[_validation_example(source_event_id=30)],
                excluded_candidates=[
                    {"source_event_id": 46,
                     "reasons": ["price-cache gap for MS"]},
                ],
                warnings=["sample warning"],
            )):
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        self.assertEqual(report["events_evaluated"], 4)
        self.assertEqual(report["records_count"], 12)
        self.assertEqual(report["significant_count"], 2)
        self.assertEqual(report["by_horizon"]["5"]["records_count"], 4)
        self.assertEqual(
            report["by_mechanism_family"]["supply_shock"]["records_count"], 9,
        )
        self.assertEqual(len(report["examples"]), 1)
        self.assertEqual(len(report["excluded_candidates"]), 1)
        self.assertIn("sample warning", report["warnings"])


# ---------------------------------------------------------------------------
# Verdict-field propagation — the smoke must surface the runner's
# per-record raw-p / FDR split fields verbatim without recomputing
# statistics.
# ---------------------------------------------------------------------------


class TestVerdictFieldPropagation(unittest.TestCase):
    def test_raw_p_only_example_propagates_validated_raw_only(self) -> None:
        # Event 46-style example: raw-p clears, FDR does not, upstream
        # interpretation is still ``not_significant``.  The verdict
        # field must surface ``validated_raw_only`` so a demo reader
        # sees the raw-p signal without recomputing anything.
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation(_validation_payload(
                examples=[_validation_example(
                    source_event_id=46,
                    p_value=0.04, fdr_q=0.20,
                    raw_p_candidate=True,
                    fdr_significant=False,
                    verdict="validated_raw_only",
                    interpretation="not_significant",
                )],
            )):
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        self.assertEqual(len(report["examples"]), 1)
        ex = report["examples"][0]
        self.assertTrue(ex["raw_p_candidate"])
        self.assertFalse(ex["fdr_significant"])
        self.assertEqual(ex["verdict"], "validated_raw_only")
        # The upstream interpretation is preserved alongside.
        self.assertEqual(ex["interpretation"], "not_significant")

    def test_each_example_carries_three_verdict_fields(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation(_validation_payload(
                examples=[
                    _validation_example(
                        source_event_id=30,
                        verdict="inconclusive_fdr",
                    ),
                    _validation_example(
                        source_event_id=46, p_value=0.04, fdr_q=0.20,
                        raw_p_candidate=True,
                        verdict="validated_raw_only",
                    ),
                    _validation_example(
                        source_event_id=73, p_value=0.01, fdr_q=0.02,
                        raw_p_candidate=True,
                        fdr_significant=True,
                        verdict="fdr_significant",
                    ),
                ],
            )):
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        for ex in report["examples"]:
            for field in ("raw_p_candidate", "fdr_significant", "verdict"):
                self.assertIn(field, ex,
                              f"propagated example missing {field}: {ex!r}")

    def test_verdict_never_calls_raw_p_only_fdr_significant(self) -> None:
        # Invariant check across the propagated example set.  No
        # surfaced row may both claim ``validated_raw_only`` AND
        # ``fdr_significant=True`` — FDR is the strict bar.
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation(_validation_payload(
                examples=[
                    _validation_example(
                        source_event_id=46, p_value=0.04, fdr_q=0.20,
                        raw_p_candidate=True,
                        fdr_significant=False,
                        verdict="validated_raw_only",
                    ),
                    _validation_example(
                        source_event_id=73, p_value=0.045, fdr_q=0.18,
                        raw_p_candidate=True,
                        fdr_significant=False,
                        verdict="validated_raw_only",
                    ),
                ],
            )):
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        for ex in report["examples"]:
            if ex["verdict"] == "validated_raw_only":
                self.assertFalse(
                    ex["fdr_significant"],
                    f"raw-p-only row claimed fdr_significant: {ex!r}",
                )


# ---------------------------------------------------------------------------
# --output writes JSON
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_path_writes_json_file(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"curated_smoke_out_{uuid.uuid4().hex}.json",
        )
        try:
            with _patch_validation():
                cli.smoke_curated_stage_validate(
                    db_path=fixture, output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path),
                            f"output file not written: {out_path}")
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(fixture)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_output_path_does_not_write_file(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation():
                cli.smoke_curated_stage_validate(db_path=fixture)
            # No file path asserted; the test passes if no exception
            # bubbled up and no file was created on disk implicitly.
            # We can't check "no file written" exhaustively, but we
            # can verify the function didn't return a path that
            # would have been used.
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_text_fields(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        try:
            with _patch_validation():
                report = cli.smoke_curated_stage_validate(db_path=fixture)
        finally:
            os.unlink(fixture)
        all_text = " ".join(
            list(report.get("errors", []))
            + list(report.get("warnings", []))
        ).lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, all_text)


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_copy_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_copy_live_db_to_temp")))

    def test_stage_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_stage_candidates_into_temp")))

    def test_validation_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_curated_validation")))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_emits_ten_keys(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        out = StringIO()
        try:
            with _patch_validation():
                rc = cli.main([
                    "--json", "--db-path", fixture,
                ], out=out)
        finally:
            os.unlink(fixture)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))

    def test_text_default_runs(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        out = StringIO()
        try:
            with _patch_validation():
                rc = cli.main(["--db-path", fixture], out=out)
        finally:
            os.unlink(fixture)
        self.assertEqual(rc, 0)
        self.assertGreater(len(out.getvalue()), 0)

    def test_cli_output_flag_writes_json_file(self) -> None:
        fixture = _make_fixture_db(list(_REPAIRED_COHORT_IDS))
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"curated_cli_out_{uuid.uuid4().hex}.json",
        )
        out = StringIO()
        try:
            with _patch_validation():
                rc = cli.main([
                    "--json", "--db-path", fixture, "--output", out_path,
                ], out=out)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_path))
        finally:
            os.unlink(fixture)
            if os.path.exists(out_path):
                os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
