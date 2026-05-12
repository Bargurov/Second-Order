"""Tests for ``scripts/freeze_candidate_evidence_artifact.py``.

Pin the contract:

* Read-only on every input; writes to ``--output`` only when
  explicitly passed.
* Each record carries the 12-field shape the spec requires:
  source, event_id, headline, primary_ticker, benchmark,
  mechanism_family, horizon, p_value, fdr_q, raw_p_candidate,
  fdr_significant, verdict.
* The envelope has the 16 required top-level keys.
* The artifact is a "freeze-candidate" — never "frozen".
* Limitations include the no-FDR-significant disclaimer when
  fdr_significant_count is 0.
* No banned tokens in limitations / claim lists / warnings / errors.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import freeze_candidate_evidence_artifact as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "artifact_type",
    "generated_at",
    "source_files",
    "cohort_summary",
    "records",
    "verdict_counts",
    "by_horizon",
    "by_mechanism_family",
    "review_completion",
    "duplicate_event_ids",
    "limitations",
    "evidence_claim_allowed",
    "evidence_claim_not_allowed",
    "warnings",
    "errors",
    "benchmark_sensitivity_status",
)


_REQUIRED_BENCHMARK_SENSITIVITY_FIELDS = (
    "status",
    "blocked_events",
    "required_dates",
    "local_backfill_available",
    "online_backfill_required",
    "comparison_summary",
    "limitations",
)


_REQUIRED_RECORD_FIELDS = (
    "source",
    "event_id",
    "headline",
    "primary_ticker",
    "benchmark",
    "mechanism_family",
    "horizon",
    "p_value",
    "fdr_q",
    "raw_p_candidate",
    "fdr_significant",
    "verdict",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "automatically",
    "alpha generated",
    "guaranteed",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Synthetic input fixtures
# ---------------------------------------------------------------------------


def _curated_payload(*, examples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "events_evaluated":     len({e.get("source_event_id") for e in examples}),
        "records_count":        len(examples),
        "significant_count":    sum(
            1 for e in examples if e.get("fdr_significant")
        ),
        "staged_count":         len(examples),
        "examples":             examples,
        "by_horizon":           {},
        "by_mechanism_family":  {},
        "excluded_candidates":  [],
        "errors":               [],
        "warnings":             [],
    }


def _short_horizon_payload(*, examples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok":                   True,
        "accepted_count":       len({e.get("event_id") for e in examples}),
        "events_evaluated":     len({e.get("event_id") for e in examples}),
        "records_count":        len(examples),
        "significant_count":    0,
        "examples":             examples,
        "by_horizon":           {},
        "by_mechanism_family":  {},
        "excluded_candidates":  [],
        "errors":               [],
        "warnings":             [],
        "worksheet_path":       "synthetic",
    }


def _curated_example(
    *, event_id: int, horizon: int,
    mechanism_family: str = "supply_shock",
    primary_ticker: str = "XOM",
    benchmark_ticker: str = "SPY",
    p_value: float = 0.5,
    fdr_q: float = 0.8,
    headline: str = "h",
) -> dict[str, Any]:
    return {
        "source_event_id":  event_id,
        "headline":         headline,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
        "mechanism_family": mechanism_family,
        "horizon":          horizon,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "abnormal_return":  0.01,
        "sar":              0.5,
        "ci_low":           -0.01,
        "ci_high":          0.03,
        "interpretation":   "not_significant",
        "verdict":          "inconclusive_fdr",
        "raw_p_candidate":  False,
        "fdr_significant":  False,
    }


def _xle_request_packet_payload(
    *, blocked_events_count: int = 2,
    required_dates_count: int = 10,
) -> dict[str, Any]:
    """Mirror the shape produced by
    ``scripts.xle_benchmark_backfill_request_packet
    .build_xle_benchmark_backfill_request_packet``."""
    return {
        "ok": True,
        "benchmark_ticker": "XLE",
        "blocked_events": [
            {
                "event_id":         60 + i,
                "event_date":       "2026-04-05",
                "primary_ticker":   "VLO",
                "benchmark_ticker": "XLE",
                "blocker_reason":   "estimation_window_short",
            }
            for i in range(blocked_events_count)
        ],
        "required_dates": [
            f"2026-01-{i + 1:02d}" for i in range(required_dates_count)
        ],
        "date_ranges":               [],
        "reason":                    "estimation_window_short",
        "why_local_backfill_failed": (
            "the existing local price_cache has no XLE rows for the "
            "listed dates"
        ),
        "allowed_next_step":         (
            "request explicit operator approval before invoking an "
            "online XLE backfill for the listed dates"
        ),
        "not_allowed":               [],
        "warnings":                  [],
        "errors":                    [],
    }


def _xle_preview_payload(
    *, ready_after: int = 2, blocked_after: int = 0,
    added_rows_count: int = 0,
) -> dict[str, Any]:
    """Mirror the shape produced by
    ``scripts.xle_benchmark_sensitivity_backfill_smoke``."""
    checked = ready_after + blocked_after
    return {
        "ok":                        True,
        "temp_db_path":              "/tmp/xle_smoke.db",
        "checked_events_before":     checked,
        "checked_events_after":      checked,
        "ready_before":              0,
        "ready_after":               ready_after,
        "blocked_before":            checked,
        "blocked_after":             blocked_after,
        "added_rows": [
            {"ticker": "XLE", "date": f"2026-01-{i + 1:02d}",
             "source": "local_cache_row_carry_forward"}
            for i in range(added_rows_count)
        ],
        "still_missing_ranges":      [],
        "live_db_unchanged":         True,
        "warnings":                  [],
        "errors":                    [],
        "recommended_next_action":   (
            "preview only; the live cache is untouched"
        ),
    }


def _xle_comparison_payload() -> dict[str, Any]:
    """Synthetic comparison artifact carrying a small summary payload.
    The script copies this through to ``comparison_summary`` (with
    bulky list fields trimmed).
    """
    return {
        "ok":            True,
        "benchmark_a":   "SPY",
        "benchmark_b":   "XLE",
        "summary": {
            "events_evaluated":     2,
            "horizons_evaluated":   3,
            "records_count":        6,
            "comparison_note":      "synthetic test fixture",
        },
        "by_event":      [],
    }


def _sh_example(
    *, event_id: int, horizon: int,
    mechanism_family: str = "supply_shock",
    primary_ticker: str = "XOM",
    benchmark: str = "SPY",
    p_value: float = 0.5,
    fdr_q: float = 0.8,
    headline: str = "h",
) -> dict[str, Any]:
    return {
        "event_id":         event_id,
        "headline":         headline,
        "primary_ticker":   primary_ticker,
        "benchmark":        benchmark,
        "mechanism_family": mechanism_family,
        "horizon":          horizon,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "abnormal_return":  0.01,
        "sar":              0.5,
        "ci_low":           -0.01,
        "ci_high":          0.03,
        "interpretation":   "not_significant",
    }


# ---------------------------------------------------------------------------
# Filesystem fixture builder
# ---------------------------------------------------------------------------


class _Workspace:
    """Build a tempdir carrying synthetic input artifacts so the
    artifact builder can be invoked end-to-end without touching the
    real artifacts/ directory."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix=f"fce_ws_{uuid.uuid4().hex}_"))
        self.curated_path = self.root / "curated.json"
        self.batches: list[tuple[str, str, str]] = []

    def write_curated(self, examples: list[dict[str, Any]]) -> str:
        self.curated_path.write_text(
            json.dumps(_curated_payload(examples=examples)),
            encoding="utf-8",
        )
        return str(self.curated_path)

    def write_batch(
        self, name: str, *,
        worksheet_rows: list[dict[str, str]] | None = None,
        validation_examples: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str, str]:
        ws_path = self.root / f"{name}.csv"
        val_path = self.root / f"{name}_validation.json"
        # Worksheet CSV — minimal 16-column schema reusing the gate.
        import csv as _csv
        cols = (
            "event_id", "headline", "event_date",
            "current_primary_ticker", "current_mechanism_family",
            "repair_type", "repair_priority",
            "operator_decision_needed", "reason_for_review",
            "proposed_primary_ticker", "proposed_benchmark_ticker",
            "proposed_mechanism_family", "predicted_direction",
            "include_in_short_horizon_validation",
            "exclude_reason", "operator_notes",
        )
        with open(ws_path, "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh, lineterminator="\n")
            w.writerow(cols)
            for r in worksheet_rows or []:
                w.writerow([str(r.get(c, "")) for c in cols])
        val_path.write_text(
            json.dumps(_short_horizon_payload(
                examples=validation_examples or [],
            )),
            encoding="utf-8",
        )
        entry = (name, str(ws_path), str(val_path))
        self.batches.append(entry)
        return entry

    def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10")
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            for k in _REQUIRED_ENVELOPE_KEYS:
                self.assertIn(k, report, f"missing key: {k}")
        finally:
            ws.cleanup()

    def test_artifact_type_is_freeze_candidate_evidence(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(
                report["artifact_type"], "freeze_candidate_evidence",
            )
        finally:
            ws.cleanup()

    def test_artifact_never_called_frozen(self) -> None:
        # The spec explicitly forbids 'frozen' wording — the artifact
        # is always 'freeze_candidate' until operator approval.
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                generated_at="2026-05-12T00:00:00Z",
            )
            blob = json.dumps(report).lower()
            self.assertNotIn("\"frozen\"", blob)
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


class TestRecordShape(unittest.TestCase):
    def test_curated_records_carry_12_fields(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([
                _curated_example(event_id=30, horizon=1),
                _curated_example(event_id=30, horizon=5),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(len(report["records"]), 2)
            for rec in report["records"]:
                self.assertEqual(
                    set(rec.keys()), set(_REQUIRED_RECORD_FIELDS),
                )
        finally:
            ws.cleanup()

    def test_short_horizon_records_carry_12_fields(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=40, horizon=1),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(len(report["records"]), 1)
            rec = report["records"][0]
            self.assertEqual(
                set(rec.keys()), set(_REQUIRED_RECORD_FIELDS),
            )
            self.assertEqual(rec["source"], "short_horizon_top10")
            self.assertEqual(rec["event_id"], 40)
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestRecordClassification(unittest.TestCase):
    def test_fdr_significant_marks_record(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.01, fdr_q=0.04),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            rec = report["records"][0]
            self.assertTrue(rec["fdr_significant"])
            self.assertFalse(rec["raw_p_candidate"])
            self.assertEqual(rec["verdict"], "fdr_significant")
        finally:
            ws.cleanup()

    def test_raw_p_only_candidate(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.03, fdr_q=0.30),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            rec = report["records"][0]
            self.assertFalse(rec["fdr_significant"])
            self.assertTrue(rec["raw_p_candidate"])
            self.assertEqual(rec["verdict"], "raw_p_only_candidate")
        finally:
            ws.cleanup()

    def test_inconclusive_fdr_for_high_p_value(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.5, fdr_q=0.8),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            rec = report["records"][0]
            self.assertFalse(rec["fdr_significant"])
            self.assertFalse(rec["raw_p_candidate"])
            self.assertEqual(rec["verdict"], "inconclusive_fdr")
        finally:
            ws.cleanup()

    def test_insufficient_when_both_missing(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(
                    event_id=1, horizon=1,
                    p_value=None,  # type: ignore[arg-type]
                    fdr_q=None,    # type: ignore[arg-type]
                ),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            rec = report["records"][0]
            self.assertEqual(rec["verdict"], "insufficient")
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


class TestAggregates(unittest.TestCase):
    def test_verdict_counts_sum_to_records(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.01, fdr_q=0.04),
                _sh_example(event_id=2, horizon=1, p_value=0.03, fdr_q=0.30),
                _sh_example(event_id=3, horizon=1, p_value=0.5,  fdr_q=0.8),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            total = sum(report["verdict_counts"].values())
            self.assertEqual(total, len(report["records"]))
            self.assertEqual(report["verdict_counts"]["fdr_significant"], 1)
            self.assertEqual(
                report["verdict_counts"]["raw_p_only_candidate"], 1,
            )
        finally:
            ws.cleanup()

    def test_by_horizon_aggregates(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.01, fdr_q=0.04),
                _sh_example(event_id=1, horizon=5, p_value=0.5,  fdr_q=0.8),
                _sh_example(event_id=2, horizon=1, p_value=0.03, fdr_q=0.30),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            by_h = report["by_horizon"]
            self.assertEqual(by_h["1"]["records_count"], 2)
            self.assertEqual(by_h["1"]["fdr_significant_count"], 1)
            self.assertEqual(by_h["1"]["raw_p_candidate_count"], 1)
            self.assertEqual(by_h["5"]["records_count"], 1)
            self.assertEqual(by_h["5"]["fdr_significant_count"], 0)
        finally:
            ws.cleanup()

    def test_by_mechanism_family_aggregates(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(
                    event_id=1, horizon=1,
                    mechanism_family="supply_shock",
                ),
                _sh_example(
                    event_id=1, horizon=5,
                    mechanism_family="supply_shock",
                ),
                _sh_example(
                    event_id=2, horizon=1,
                    mechanism_family="chokepoint_relief",
                ),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            fam = report["by_mechanism_family"]
            self.assertEqual(fam["supply_shock"]["records_count"], 2)
            self.assertEqual(fam["supply_shock"]["events_evaluated"], 1)
            self.assertEqual(fam["chokepoint_relief"]["records_count"], 1)
            self.assertEqual(fam["chokepoint_relief"]["events_evaluated"], 1)
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Limitations
# ---------------------------------------------------------------------------


class TestLimitations(unittest.TestCase):
    def test_no_fdr_significant_disclaimer_when_count_is_zero(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.5, fdr_q=0.8),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            joined = " ".join(report["limitations"]).lower()
            self.assertIn("no fdr-significant validation claim", joined)
            self.assertEqual(
                report["cohort_summary"]["fdr_significant_count"], 0,
            )
        finally:
            ws.cleanup()

    def test_no_fdr_disclaimer_absent_when_at_least_one_fdr_significant(
        self,
    ) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.01, fdr_q=0.04),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            joined = " ".join(report["limitations"]).lower()
            self.assertNotIn("no fdr-significant validation claim", joined)
        finally:
            ws.cleanup()

    def test_default_disclaimer_always_present(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                generated_at="2026-05-12T00:00:00Z",
            )
            joined = " ".join(report["limitations"]).lower()
            self.assertIn("freeze-candidate only", joined)
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Review completion (incl. final8 zero-records)
# ---------------------------------------------------------------------------


class TestReviewCompletion(unittest.TestCase):
    def test_final8_zero_records_still_listed(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            # final8 worksheet has 8 'no' rows, validation has 0 records.
            no_rows = [
                {"event_id": str(100 + i),
                 "include_in_short_horizon_validation": "no",
                 "exclude_reason": "off-topic"}
                for i in range(8)
            ]
            ws.write_batch(
                "final8",
                worksheet_rows=no_rows,
                validation_examples=[],
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(len(report["review_completion"]), 1)
            entry = report["review_completion"][0]
            self.assertEqual(entry["name"], "final8")
            self.assertEqual(entry["worksheet_total_rows"], 8)
            self.assertEqual(entry["accepted_count"], 0)
            self.assertEqual(entry["excluded_count"], 8)
            self.assertEqual(entry["pending_count"], 0)
            self.assertEqual(entry["records_count"], 0)
        finally:
            ws.cleanup()

    def test_review_completion_tracks_yes_no_pending(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            rows = (
                [{"event_id": "1",
                  "include_in_short_horizon_validation": "yes"}] * 2
                + [{"event_id": "2",
                    "include_in_short_horizon_validation": "no",
                    "exclude_reason": "x"}] * 3
                + [{"event_id": "3",
                    "include_in_short_horizon_validation": ""}] * 4
            )
            ws.write_batch("top10", worksheet_rows=rows)
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            entry = report["review_completion"][0]
            self.assertEqual(entry["accepted_count"], 2)
            self.assertEqual(entry["excluded_count"], 3)
            self.assertEqual(entry["pending_count"], 4)
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Duplicate event_ids across sources
# ---------------------------------------------------------------------------


class TestDuplicateEventIds(unittest.TestCase):
    def test_event_id_appearing_in_curated_and_short_horizon_surfaced(
        self,
    ) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([
                _curated_example(event_id=30, horizon=1),
            ])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=30, horizon=1),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(report["duplicate_event_ids"], [30])
        finally:
            ws.cleanup()

    def test_distinct_event_ids_yield_empty_duplicate_list(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([
                _curated_example(event_id=10, horizon=1),
            ])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=20, horizon=1),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(report["duplicate_event_ids"], [])
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Output file persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_no_output_means_no_file(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10")
            sentinel = ws.root / "should_not_exist.json"
            self.assertFalse(sentinel.exists())
            cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertFalse(sentinel.exists())
        finally:
            ws.cleanup()

    def test_output_writes_file(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10")
            out_path = ws.root / "artifact.json"
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                output_path=str(out_path),
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertTrue(out_path.exists())
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(
                data["artifact_type"], "freeze_candidate_evidence",
            )
            self.assertEqual(set(data.keys()), set(_REQUIRED_ENVELOPE_KEYS))
            self.assertEqual(data["ok"], report["ok"])
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Source files presence reporting
# ---------------------------------------------------------------------------


class TestSourceFiles(unittest.TestCase):
    def test_missing_curated_surfaces_warning(self) -> None:
        ws = _Workspace()
        try:
            ws.write_batch("top10")
            missing_curated = ws.root / "absent_curated.json"
            self.assertFalse(missing_curated.exists())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(missing_curated),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertTrue(any(
                "curated" in w.lower() and "missing" in w.lower()
                for w in report["warnings"]
            ))
            # Source files entry still includes the missing path with
            # present=False so a consumer can see what was expected.
            entries = [
                e for e in report["source_files"]
                if e.get("kind") == "curated_stage_validation"
            ]
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0]["present"])
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_limitations_or_claims(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            ws.write_batch("top10", validation_examples=[
                _sh_example(event_id=1, horizon=1, p_value=0.5, fdr_q=0.8),
            ])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=ws.batches,
                generated_at="2026-05-12T00:00:00Z",
            )
            text = " ".join([
                *report["limitations"],
                *report["evidence_claim_allowed"],
                *report["evidence_claim_not_allowed"],
                *report["warnings"],
                *[str(e) for e in report["errors"]],
            ]).lower()
            for term in _BANNED_WORDS:
                self.assertNotIn(
                    term, text,
                    f"banned token {term!r} in artifact prose",
                )
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"artifact builder must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, out.getvalue()

    def test_json_output_carries_required_keys(self) -> None:
        rc, output = self._run(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)

    def test_text_render_runs(self) -> None:
        rc, output = self._run([])
        self.assertEqual(rc, 0)
        self.assertIn("freeze-candidate", output.lower())


# ---------------------------------------------------------------------------
# Benchmark sensitivity appendix
# ---------------------------------------------------------------------------


class TestBenchmarkSensitivityStatus(unittest.TestCase):
    def _write(self, ws: "_Workspace", name: str,
               payload: dict[str, Any]) -> str:
        path = ws.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def _nope(self, ws: "_Workspace", name: str) -> str:
        # Path that does not exist — defeats default-path lookup so
        # tests stay isolated from the live artifacts/ directory.
        return str(ws.root / name)

    def test_block_present_in_envelope(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertIn("benchmark_sensitivity_status", report)
        finally:
            ws.cleanup()

    def test_block_has_all_seven_required_fields(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            for f in _REQUIRED_BENCHMARK_SENSITIVITY_FIELDS:
                self.assertIn(f, block, f"missing field: {f}")
        finally:
            ws.cleanup()

    def test_status_unknown_when_no_artifacts(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(
                report["benchmark_sensitivity_status"]["status"], "unknown",
            )
        finally:
            ws.cleanup()

    def test_status_blocked_when_only_request_packet_exists(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(
                report["benchmark_sensitivity_status"]["status"], "blocked",
            )
        finally:
            ws.cleanup()

    def test_status_preview_ready_when_blocked_after_zero(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            prev = self._write(
                ws, "preview.json",
                _xle_preview_payload(ready_after=2, blocked_after=0),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=prev,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(
                report["benchmark_sensitivity_status"]["status"],
                "preview_ready",
            )
        finally:
            ws.cleanup()

    def test_status_remains_blocked_when_preview_still_blocked(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            prev = self._write(
                ws, "preview.json",
                _xle_preview_payload(ready_after=1, blocked_after=1),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=prev,
                generated_at="2026-05-12T00:00:00Z",
            )
            # blocked_after > 0 — preflight has not cleared, so status
            # is still 'blocked', not 'preview_ready'.
            self.assertEqual(
                report["benchmark_sensitivity_status"]["status"], "blocked",
            )
        finally:
            ws.cleanup()

    def test_status_comparison_available_takes_priority(self) -> None:
        # Even when a request packet documents blocked events AND a
        # preview shows ready_after=2 / blocked_after=0, a comparison
        # artifact dominates and lands the status at
        # 'comparison_available'.
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            prev = self._write(
                ws, "preview.json",
                _xle_preview_payload(ready_after=2, blocked_after=0),
            )
            cmp_ = self._write(ws, "cmp.json", _xle_comparison_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=prev,
                xle_comparison_path=cmp_,
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertEqual(
                report["benchmark_sensitivity_status"]["status"],
                "comparison_available",
            )
        finally:
            ws.cleanup()

    def test_blocked_events_propagated_from_request_packet(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(
                ws, "req.json",
                _xle_request_packet_payload(blocked_events_count=3),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertEqual(len(block["blocked_events"]), 3)
            for be in block["blocked_events"]:
                self.assertIn("event_id", be)
                self.assertIn("benchmark_ticker", be)
        finally:
            ws.cleanup()

    def test_required_dates_propagated_from_request_packet(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(
                ws, "req.json",
                _xle_request_packet_payload(required_dates_count=7),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertEqual(len(block["required_dates"]), 7)
        finally:
            ws.cleanup()

    def test_local_backfill_available_reflects_preview_added_rows(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            prev = self._write(
                ws, "preview.json",
                _xle_preview_payload(
                    ready_after=1, blocked_after=1, added_rows_count=3,
                ),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=prev,
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertTrue(block["local_backfill_available"])
        finally:
            ws.cleanup()

    def test_local_backfill_unavailable_when_preview_added_zero(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            prev = self._write(
                ws, "preview.json",
                _xle_preview_payload(
                    ready_after=0, blocked_after=2, added_rows_count=0,
                ),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=prev,
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertFalse(block["local_backfill_available"])
        finally:
            ws.cleanup()

    def test_online_backfill_required_when_status_blocked(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertTrue(block["online_backfill_required"])
        finally:
            ws.cleanup()

    def test_online_backfill_not_required_when_preview_ready(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            prev = self._write(
                ws, "preview.json",
                _xle_preview_payload(ready_after=2, blocked_after=0),
            )
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=prev,
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertFalse(block["online_backfill_required"])
        finally:
            ws.cleanup()

    def test_comparison_summary_populated_when_comparison_present(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            cmp_ = self._write(ws, "cmp.json", _xle_comparison_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=self._nope(ws, "no_prev.json"),
                xle_comparison_path=cmp_,
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertIsNotNone(block["comparison_summary"])
            self.assertIn("summary", block["comparison_summary"])
            # Bulky list fields trimmed in the surfaced summary.
            self.assertNotIn("by_event", block["comparison_summary"])
        finally:
            ws.cleanup()

    def test_comparison_summary_is_none_when_no_comparison(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertIsNone(block["comparison_summary"])
        finally:
            ws.cleanup()

    def test_limitations_say_unavailable_when_blocked(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            self.assertEqual(block["status"], "blocked")
            joined = " ".join(block["limitations"]).lower()
            # Task: "If status=blocked, limitations must say benchmark
            # sensitivity is unavailable."
            self.assertIn("benchmark sensitivity", joined)
            self.assertIn("unavailable", joined)
        finally:
            ws.cleanup()

    def test_top_level_evidence_claim_not_allowed_includes_spy_xle(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=self._nope(ws, "no_req.json"),
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            joined = " ".join(report["evidence_claim_not_allowed"]).lower()
            self.assertIn("spy", joined)
            self.assertIn("xle", joined)
        finally:
            ws.cleanup()

    def test_no_spy_vs_xle_direction_claim_in_block_when_blocked(self) -> None:
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            block = report["benchmark_sensitivity_status"]
            joined = " ".join(str(x) for x in block["limitations"]).lower()
            # No directional / outperformance language allowed while
            # benchmark sensitivity is blocked.
            for forbidden in (
                "spy outperforms", "xle outperforms",
                "similar to spy", "similar to xle",
                "diverges from spy", "diverges from xle",
            ):
                self.assertNotIn(
                    forbidden, joined,
                    f"directional claim leaked into blocked-status text: "
                    f"{forbidden!r}",
                )
        finally:
            ws.cleanup()

    def test_block_limitations_use_conservative_language(self) -> None:
        # Audit the block's own limitations list against the same
        # banned-token set as the top-level prose check.
        ws = _Workspace()
        try:
            ws.write_curated([])
            req = self._write(ws, "req.json", _xle_request_packet_payload())
            report = cli.build_freeze_candidate_evidence_artifact(
                curated_path=str(ws.curated_path),
                short_horizon_batches=[],
                xle_request_packet_path=req,
                xle_preview_path=self._nope(ws, "no_prev.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            text = " ".join(
                report["benchmark_sensitivity_status"]["limitations"]
            ).lower()
            for term in _BANNED_WORDS:
                self.assertNotIn(term, text)
        finally:
            ws.cleanup()


# ---------------------------------------------------------------------------
# Benchmark sensitivity CLI flags
# ---------------------------------------------------------------------------


class TestCliBenchmarkSensitivityFlags(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, out.getvalue()

    def test_cli_request_packet_only_yields_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            req_p = tmp_p / "req.json"
            req_p.write_text(json.dumps(_xle_request_packet_payload()))
            # Point preview at a non-existent path so the default
            # artifacts/ path doesn't accidentally resolve.
            rc, output = self._run([
                "--json",
                "--xle-request-packet", str(req_p),
                "--xle-preview",        str(tmp_p / "missing.json"),
            ])
            self.assertEqual(rc, 0)
            parsed = json.loads(output)
            self.assertEqual(
                parsed["benchmark_sensitivity_status"]["status"], "blocked",
            )

    def test_cli_preview_ready_yields_preview_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            prev_p = tmp_p / "preview.json"
            prev_p.write_text(json.dumps(
                _xle_preview_payload(ready_after=2, blocked_after=0),
            ))
            rc, output = self._run([
                "--json",
                "--xle-request-packet", str(tmp_p / "missing.json"),
                "--xle-preview",        str(prev_p),
            ])
            self.assertEqual(rc, 0)
            parsed = json.loads(output)
            self.assertEqual(
                parsed["benchmark_sensitivity_status"]["status"],
                "preview_ready",
            )

    def test_cli_comparison_yields_comparison_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cmp_p = tmp_p / "cmp.json"
            cmp_p.write_text(json.dumps(_xle_comparison_payload()))
            rc, output = self._run([
                "--json",
                "--xle-request-packet", str(tmp_p / "missing.json"),
                "--xle-preview",        str(tmp_p / "missing.json"),
                "--xle-comparison",     str(cmp_p),
            ])
            self.assertEqual(rc, 0)
            parsed = json.loads(output)
            self.assertEqual(
                parsed["benchmark_sensitivity_status"]["status"],
                "comparison_available",
            )


if __name__ == "__main__":
    unittest.main()
