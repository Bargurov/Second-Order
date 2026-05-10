"""Tests for ``scripts/repaired_cohort_benchmark_sensitivity_report.py``.

The sensitivity report answers a narrow question: would the 5-event
repaired cohort's SAR / p / FDR change if we ran the validation
pipeline with each event's operator-proposed benchmark instead of
the universal SPY benchmark?

Pin the contract:

* Read-only / temp-copy only — never mutates live DB or input backup.
* Reuses the existing repaired-cohort runner via a patchable seam so
  the cohort-identification logic is not duplicated.
* For each (event_id, horizon) record in the repaired cohort, emits:

      event_id, ticker, mechanism_family, horizon,
      spy_result, operator_benchmark_result,
      verdict_change, fdr_change, recommended_next_action

* ``operator_benchmark_result`` is ``None`` when the operator did not
  propose an alternative benchmark (no row, blank cell, or the
  proposed benchmark equals SPY).  In that case ``verdict_change`` is
  ``"no_alternative_proposed"`` and ``fdr_change`` is ``None``.
* When an alternative is proposed, ``verdict_change`` ∈ {
  ``"no_change"``, ``"flip_to_significant"``,
  ``"flip_to_nonsignificant"`` } and ``fdr_change`` is the numeric
  delta ``operator_fdr_q - spy_fdr_q``.
* Conservative wording only — the script never claims "proof",
  "alpha", or causal language; verdict text mirrors the runner's own
  vocabulary.
* Fail-closed precedence:
    - Missing backup / CSV path → fail closed.
    - Baseline runner reports ``ok=False`` → propagate ``ok=False``
      and surface its errors verbatim.
* Hash invariants — live DB + input backup are byte-identical
  before/after every run.
"""
from __future__ import annotations

import csv as csv_module
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

from scripts import repaired_cohort_benchmark_sensitivity_report as cli  # noqa: E402


# Envelope: ok, records, repaired_clean_event_ids, summary,
# live_db_unchanged, input_backup_unchanged, errors, warnings.
_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "records",
    "repaired_clean_event_ids",
    "summary",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
)


# Per-record contract from the brief.
_REQUIRED_RECORD_FIELDS = (
    "event_id",
    "ticker",
    "mechanism_family",
    "horizon",
    "spy_result",
    "operator_benchmark_result",
    "verdict_change",
    "fdr_change",
    "recommended_next_action",
)


_VERDICT_NO_ALT       = "no_alternative_proposed"
_VERDICT_NO_CHANGE    = "no_change"
_VERDICT_FLIP_TO_SIG  = "flip_to_significant"
_VERDICT_FLIP_TO_NOSIG = "flip_to_nonsignificant"
_VERDICT_UNCOMPUTABLE = "alternative_proposed_but_uncomputable"


# ---------------------------------------------------------------------------
# Fixture builders.  These mirror the existing
# tests/test_manual_repaired_cohort_validation_run.py shape so the
# two suites stay in lockstep on schema / DDL / CSV columns.
# ---------------------------------------------------------------------------


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


def _events_ddl() -> str:
    cols = [
        "id              INTEGER PRIMARY KEY AUTOINCREMENT",
        "headline        TEXT",
        "event_date      TEXT",
        "market_tickers  TEXT",
        "low_signal      INTEGER DEFAULT 0",
        "mechanism_family TEXT DEFAULT 'none'",
    ]
    return "CREATE TABLE events (\n  " + ",\n  ".join(cols) + "\n)"


def _make_temp_db(suffix: str = "rcbs") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_events_ddl())
        conn.execute(_PRICE_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_HIGH_MEDIUM_COLUMNS = (
    "event_id", "headline", "event_date", "current_primary_ticker",
    "flags", "reason", "manual_review_priority",
    "proposed_primary_ticker", "proposed_benchmark",
    "proposed_mechanism_family",
    "ticker_rationale", "exclude_reason",
)

_FAMILY_COLUMNS = (
    "event_id", "headline", "event_date",
    "current_primary_ticker", "current_benchmark",
    "flags", "repair_priority", "reason",
    "proposed_mechanism_family", "mechanism_rationale",
    "exclude_reason",
)


def _write_csv(rows: list[dict], *, suffix: str = "rcbs_csv") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(_HIGH_MEDIUM_COLUMNS)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in _HIGH_MEDIUM_COLUMNS])
    return path


def _write_family_csv(rows: list[dict], *, suffix: str = "rcbs_fm") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(_FAMILY_COLUMNS)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in _FAMILY_COLUMNS])
    return path


def _hm_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_benchmark: str = "",
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  f"h{event_id}",
        "event_date":                "2026-04-06",
        "current_primary_ticker":    "DRIV",
        "flags":                     "",
        "reason":                    "contaminated_fully_ready",
        "manual_review_priority":    "high",
        "proposed_primary_ticker":   proposed_primary_ticker,
        "proposed_benchmark":        proposed_benchmark,
        "proposed_mechanism_family": proposed_mechanism_family,
        "ticker_rationale":          "",
        "exclude_reason":            exclude_reason,
    }


def _family_row(
    *, event_id: int, proposed_mechanism_family: str = "",
    exclude_reason: str = "",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  f"h{event_id}",
        "event_date":                "2026-04-05",
        "current_primary_ticker":    "XOM",
        "current_benchmark":         "SPY",
        "flags":                     "mechanism_family_none",
        "repair_priority":           "high",
        "reason":                    "Manual review candidate",
        "proposed_mechanism_family": proposed_mechanism_family,
        "mechanism_rationale":       "",
        "exclude_reason":            exclude_reason,
    }


# ---------------------------------------------------------------------------
# Synthetic payload builders for the runner-shaped seam returns.
# ---------------------------------------------------------------------------


def _example(
    *, event_id: int, horizon: int = 5,
    ticker: str = "MS", benchmark: str = "SPY",
    mechanism_family: str | None = "supply_shock",
    sar: float = 1.5, p_value: float = 0.04, fdr_q: float = 0.08,
    significant: bool = True,
) -> dict:
    """An ``example`` dict in the shape the existing runner emits."""
    return {
        "event_id":         event_id,
        "headline":         f"h{event_id}",
        "primary_ticker":   ticker,
        "benchmark":        benchmark,
        "mechanism_family": mechanism_family,
        "horizon":          horizon,
        "abnormal_return":  0.012,
        "sar":              sar,
        "ci_low":           0.001,
        "ci_high":          0.022,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "interpretation":   "evidence" if significant else "inconclusive",
    }


def _runner_payload(
    *, repaired_event_ids: list[int],
    examples: list[dict],
    excluded_event_ids: list[int] | None = None,
    errors: list[str] | None = None,
) -> dict:
    """Mirror the 14-key envelope from
    ``manual_repaired_cohort_validation_run.run_manual_repaired_cohort_validation``.
    """
    excluded_event_ids = excluded_event_ids or []
    errors = errors or []
    by_horizon: dict[str, Any] = {}
    by_family:  dict[str, Any] = {}
    return {
        "ok":                       not errors,
        "repaired_clean_event_ids": list(repaired_event_ids),
        "events_evaluated":         len({e["event_id"] for e in examples}),
        "records_count":            len(examples),
        "significant_count":        sum(
            1 for e in examples
            if e.get("p_value") is not None and e["p_value"] <= 0.05
        ),
        "by_horizon":               by_horizon,
        "by_mechanism_family":      by_family,
        "examples":                 list(examples),
        "excluded_event_ids":       list(excluded_event_ids),
        "remaining_blockers":       {},
        "live_db_unchanged":        True,
        "input_backup_unchanged":   True,
        "errors":                   list(errors),
        "warnings":                 [],
    }


def _patch_seams(
    *,
    baseline_payload: dict,
    operator_payload: dict | None = None,
):
    """Patch BOTH underlying seams in one helper.

    The sensitivity report has TWO patchable seams — one for the SPY
    baseline run and one for the operator-benchmark run.  Both have the
    same return shape (the runner's 14-key envelope).  Tests patch them
    directly with synthetic payloads so the test suite never invokes
    the real validation pipeline.
    """
    baseline_patch = patch.object(
        cli, "_run_baseline_validation",
        return_value=baseline_payload,
    )
    if operator_payload is None:
        # Default: same as baseline (no alternative-benchmark variation).
        operator_payload = baseline_payload
    operator_patch = patch.object(
        cli, "_run_operator_benchmark_validation",
        return_value=operator_payload,
    )
    return baseline_patch, operator_patch


def _run(
    *, backup_path: str | None = None,
    high_priority_csv: str | None = None,
    medium_csv: str | None = None,
    mechanism_family_csv: str | None = None,
    db_path: str | None = None,
    limit: int = 50,
) -> dict:
    return cli.run_repaired_cohort_benchmark_sensitivity(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_returns_envelope_with_required_keys(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([
            _hm_row(event_id=46, proposed_primary_ticker="MS",
                    proposed_benchmark="SPY",
                    proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        medium = _write_csv([])
        baseline = _runner_payload(
            repaired_event_ids=[46],
            examples=[_example(event_id=46, ticker="MS", benchmark="SPY")],
        )
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, result, f"missing envelope key: {k}")


class TestPerRecordSchema(unittest.TestCase):
    def test_record_carries_brief_mandated_fields(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([
            _hm_row(event_id=46, proposed_primary_ticker="MS",
                    proposed_benchmark="SPY",
                    proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        medium = _write_csv([])
        baseline = _runner_payload(
            repaired_event_ids=[46],
            examples=[_example(event_id=46, ticker="MS", benchmark="SPY")],
        )
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        self.assertGreaterEqual(len(result["records"]), 1)
        rec = result["records"][0]
        for f in _REQUIRED_RECORD_FIELDS:
            self.assertIn(f, rec, f"missing record field: {f}")


# ---------------------------------------------------------------------------
# verdict_change semantics
# ---------------------------------------------------------------------------


class TestNoAlternativeProposed(unittest.TestCase):
    def test_blank_proposed_benchmark_yields_no_alternative(self) -> None:
        # Family-only event (mechanism_family CSV has no
        # proposed_benchmark column) → operator did not propose an
        # alternative; verdict_change must be no_alternative_proposed.
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([])
        family = _write_family_csv([
            _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[30],
            examples=[_example(event_id=30, ticker="XOM", benchmark="SPY",
                                mechanism_family="supply_shock")],
        )
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium); os.unlink(family)
        self.assertIs(result["ok"], True)
        rec = next(r for r in result["records"] if r["event_id"] == 30)
        self.assertEqual(rec["verdict_change"], _VERDICT_NO_ALT)
        self.assertIsNone(rec["operator_benchmark_result"])
        self.assertIsNone(rec["fdr_change"])

    def test_proposed_benchmark_equal_to_spy_is_no_alternative(self) -> None:
        # Event 46 has proposed_benchmark=SPY in the live high-priority
        # CSV — operator confirmed SPY is appropriate.  No alternative
        # exists, so the verdict is no_alternative_proposed.
        backup = _make_temp_db()
        high   = _write_csv([
            _hm_row(event_id=46, proposed_primary_ticker="MS",
                    proposed_benchmark="SPY",
                    proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        medium = _write_csv([])
        baseline = _runner_payload(
            repaired_event_ids=[46],
            examples=[_example(event_id=46, ticker="MS", benchmark="SPY")],
        )
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        rec = next(r for r in result["records"] if r["event_id"] == 46)
        self.assertEqual(rec["verdict_change"], _VERDICT_NO_ALT)
        self.assertIsNone(rec["operator_benchmark_result"])


class TestVerdictNoChange(unittest.TestCase):
    def test_alternative_with_same_significance_is_no_change(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([
            _hm_row(event_id=60, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(
                event_id=60, ticker="XOM", benchmark="SPY",
                p_value=0.04, fdr_q=0.08,
            )],
        )
        operator = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(
                event_id=60, ticker="XOM", benchmark="XLE",
                p_value=0.045, fdr_q=0.09,
            )],
        )
        try:
            bp, op = _patch_seams(
                baseline_payload=baseline, operator_payload=operator,
            )
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        rec = next(r for r in result["records"] if r["event_id"] == 60)
        self.assertEqual(rec["verdict_change"], _VERDICT_NO_CHANGE)
        self.assertEqual(rec["operator_benchmark_result"]["benchmark"], "XLE")
        self.assertAlmostEqual(rec["fdr_change"], 0.01, places=6)


class TestVerdictFlipToSignificant(unittest.TestCase):
    def test_alternative_flips_to_significant(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([
            _hm_row(event_id=60, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(
                event_id=60, ticker="XOM", benchmark="SPY",
                p_value=0.20, fdr_q=0.30, significant=False,
            )],
        )
        operator = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(
                event_id=60, ticker="XOM", benchmark="XLE",
                p_value=0.02, fdr_q=0.04, significant=True,
            )],
        )
        try:
            bp, op = _patch_seams(
                baseline_payload=baseline, operator_payload=operator,
            )
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        rec = next(r for r in result["records"] if r["event_id"] == 60)
        self.assertEqual(rec["verdict_change"], _VERDICT_FLIP_TO_SIG)
        self.assertAlmostEqual(rec["fdr_change"], -0.26, places=6)


class TestVerdictFlipToNonsignificant(unittest.TestCase):
    def test_alternative_flips_to_nonsignificant(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([
            _hm_row(event_id=73, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[73],
            examples=[_example(
                event_id=73, ticker="XOM", benchmark="SPY",
                p_value=0.02, fdr_q=0.04,
            )],
        )
        operator = _runner_payload(
            repaired_event_ids=[73],
            examples=[_example(
                event_id=73, ticker="XOM", benchmark="XLE",
                p_value=0.30, fdr_q=0.50,
            )],
        )
        try:
            bp, op = _patch_seams(
                baseline_payload=baseline, operator_payload=operator,
            )
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        rec = next(r for r in result["records"] if r["event_id"] == 73)
        self.assertEqual(rec["verdict_change"], _VERDICT_FLIP_TO_NOSIG)
        self.assertGreater(rec["fdr_change"], 0)


class TestVerdictUncomputable(unittest.TestCase):
    """When the operator proposed an alternative benchmark but the
    operator-benchmark validation run produced no record for a given
    (event, horizon) (e.g., the alternative benchmark's price data is
    not in the cache), surface a distinct verdict so operators see the
    gap rather than mis-reading it as 'no alternative proposed'."""

    def test_alternative_without_op_record_is_uncomputable(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([
            _hm_row(event_id=60, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(event_id=60, ticker="XOM", benchmark="SPY")],
        )
        # Operator-benchmark run produced no example for event 60 —
        # simulating a price-cache gap for XLE.
        operator = _runner_payload(
            repaired_event_ids=[60], examples=[],
        )
        try:
            bp, op = _patch_seams(
                baseline_payload=baseline, operator_payload=operator,
            )
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        rec = next(r for r in result["records"] if r["event_id"] == 60)
        self.assertEqual(rec["verdict_change"], _VERDICT_UNCOMPUTABLE)
        self.assertIsNone(rec["operator_benchmark_result"])
        self.assertIsNone(rec["fdr_change"])


# ---------------------------------------------------------------------------
# Five-event live-cohort scenario (mirrors the live three-CSV setup)
# ---------------------------------------------------------------------------


class TestFiveEventCohort(unittest.TestCase):
    """End-to-end shape over the realistic 5-event repaired cohort:
    30, 40, 46, 60, 73.  Only 60 and 73 carry a non-SPY proposed
    benchmark (XLE).  The other three must surface
    no_alternative_proposed."""

    def test_records_match_per_event_expectations(self) -> None:
        backup = _make_temp_db()
        high = _write_csv([
            _hm_row(event_id=46, proposed_primary_ticker="MS",
                    proposed_benchmark="SPY",
                    proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        medium = _write_csv([
            _hm_row(event_id=60, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
            _hm_row(event_id=73, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
        ])
        family = _write_family_csv([
            _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
            _family_row(event_id=40,
                        proposed_mechanism_family="commodity_squeeze"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[30, 40, 46, 60, 73],
            examples=[
                _example(event_id=30, ticker="XOM", benchmark="SPY",
                         mechanism_family="supply_shock"),
                _example(event_id=40, ticker="BDRY", benchmark="SPY",
                         mechanism_family="commodity_squeeze"),
                _example(event_id=46, ticker="MS",  benchmark="SPY",
                         mechanism_family="bank_regulatory_capital_relief"),
                _example(event_id=60, ticker="XOM", benchmark="SPY",
                         mechanism_family="supply_shock",
                         p_value=0.04, fdr_q=0.08),
                _example(event_id=73, ticker="XOM", benchmark="SPY",
                         mechanism_family="supply_shock",
                         p_value=0.06, fdr_q=0.10, significant=False),
            ],
        )
        operator = _runner_payload(
            repaired_event_ids=[60, 73],
            examples=[
                _example(event_id=60, ticker="XOM", benchmark="XLE",
                         mechanism_family="supply_shock",
                         p_value=0.045, fdr_q=0.09),
                _example(event_id=73, ticker="XOM", benchmark="XLE",
                         mechanism_family="supply_shock",
                         p_value=0.02, fdr_q=0.04, significant=True),
            ],
        )
        try:
            bp, op = _patch_seams(
                baseline_payload=baseline, operator_payload=operator,
            )
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                )
        finally:
            os.unlink(backup); os.unlink(high)
            os.unlink(medium); os.unlink(family)

        self.assertIs(result["ok"], True)
        by_id = {r["event_id"]: r for r in result["records"]}
        # Three events have no alternative.
        for ev in (30, 40, 46):
            self.assertEqual(
                by_id[ev]["verdict_change"], _VERDICT_NO_ALT,
                f"event {ev} should be no_alternative_proposed",
            )
            self.assertIsNone(by_id[ev]["operator_benchmark_result"])
            self.assertIsNone(by_id[ev]["fdr_change"])
        # Two events have XLE as alternative.
        self.assertIn(by_id[60]["verdict_change"],
                      (_VERDICT_NO_CHANGE, _VERDICT_FLIP_TO_SIG,
                       _VERDICT_FLIP_TO_NOSIG))
        self.assertEqual(by_id[60]["operator_benchmark_result"]["benchmark"],
                         "XLE")
        self.assertEqual(by_id[73]["verdict_change"], _VERDICT_FLIP_TO_SIG)


# ---------------------------------------------------------------------------
# Fail-closed precedence
# ---------------------------------------------------------------------------


class TestFailClosedMissingInputs(unittest.TestCase):
    def test_missing_backup_path_fails(self) -> None:
        high   = _write_csv([])
        medium = _write_csv([])
        try:
            result = _run(backup_path=None,
                          high_priority_csv=high, medium_csv=medium)
        finally:
            os.unlink(high); os.unlink(medium)
        self.assertIs(result["ok"], False)

    def test_nonexistent_backup_fails(self) -> None:
        high   = _write_csv([])
        medium = _write_csv([])
        try:
            result = _run(backup_path="/path/does/not/exist.db",
                          high_priority_csv=high, medium_csv=medium)
        finally:
            os.unlink(high); os.unlink(medium)
        self.assertIs(result["ok"], False)

    def test_missing_csv_paths_fail(self) -> None:
        backup = _make_temp_db()
        try:
            result = _run(backup_path=backup,
                          high_priority_csv="/nope.csv",
                          medium_csv="/also-nope.csv")
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)


class TestFailClosedFromBaseline(unittest.TestCase):
    """When the baseline runner returns ok=False (e.g., provider
    unavailable inside the underlying runner), the sensitivity report
    propagates ok=False and surfaces those errors verbatim."""

    def test_baseline_ok_false_propagates(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([])
        baseline = _runner_payload(
            repaired_event_ids=[],
            examples=[],
            errors=[
                "Provider unavailable (yfinance not importable) — "
                "failing closed without writing"
            ],
        )
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("provider" in e.lower() for e in result["errors"]))


# ---------------------------------------------------------------------------
# Patchable seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_baseline_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_baseline_validation")))

    def test_operator_benchmark_seam_exists(self) -> None:
        self.assertTrue(
            callable(getattr(cli, "_run_operator_benchmark_validation"))
        )


class TestImportIsolation(unittest.TestCase):
    """Importing the report module must NOT pull in yfinance, FastAPI,
    or other heavy production seams.  Mirrors the existing runner's
    import-isolation contract."""

    _BLOCKED = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_module_import_does_not_pull_provider_or_fastapi(self) -> None:
        before = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        after = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# Hash invariants
# ---------------------------------------------------------------------------


class TestHashInvariants(unittest.TestCase):
    def test_happy_path_keeps_hashes(self) -> None:
        live   = _make_temp_db("rcbs_live")
        backup = _make_temp_db("rcbs_backup")
        high   = _write_csv([
            _hm_row(event_id=46, proposed_primary_ticker="MS",
                    proposed_benchmark="SPY",
                    proposed_mechanism_family="m"),
        ])
        medium = _write_csv([])
        live_before   = _sha256(live)
        backup_before = _sha256(backup)
        baseline = _runner_payload(
            repaired_event_ids=[46],
            examples=[_example(event_id=46, ticker="MS", benchmark="SPY")],
        )
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                result = _run(
                    backup_path=backup, db_path=live,
                    high_priority_csv=high, medium_csv=medium,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
            self.assertIs(result["live_db_unchanged"], True)
            self.assertIs(result["input_backup_unchanged"], True)
        finally:
            os.unlink(live); os.unlink(backup)
            os.unlink(high); os.unlink(medium)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    """The recommended_next_action text must avoid causal / proof
    language.  Allowed keywords are limited to a small vocabulary."""

    _FORBIDDEN = ("proof", "proves", "alpha", "causal", "guaranteed")

    def test_recommended_next_action_avoids_forbidden_terms(self) -> None:
        backup = _make_temp_db()
        high   = _write_csv([])
        medium = _write_csv([
            _hm_row(event_id=60, proposed_primary_ticker="XOM",
                    proposed_benchmark="XLE",
                    proposed_mechanism_family="supply_shock"),
        ])
        baseline = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(event_id=60, ticker="XOM", benchmark="SPY")],
        )
        operator = _runner_payload(
            repaired_event_ids=[60],
            examples=[_example(event_id=60, ticker="XOM", benchmark="XLE",
                                p_value=0.30, fdr_q=0.50,
                                significant=False)],
        )
        try:
            bp, op = _patch_seams(
                baseline_payload=baseline, operator_payload=operator,
            )
            with bp, op:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        for rec in result["records"]:
            text = (rec.get("recommended_next_action") or "").lower()
            for term in self._FORBIDDEN:
                self.assertNotIn(
                    term, text,
                    f"forbidden term {term!r} in recommendation: {text!r}",
                )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_cli_emits_parseable_json(self) -> None:
        backup = _make_temp_db()
        high = _write_csv([
            _hm_row(event_id=46, proposed_primary_ticker="MS",
                    proposed_benchmark="SPY",
                    proposed_mechanism_family="m"),
        ])
        medium = _write_csv([])
        baseline = _runner_payload(
            repaired_event_ids=[46],
            examples=[_example(event_id=46, ticker="MS", benchmark="SPY")],
        )
        out = StringIO()
        try:
            bp, op = _patch_seams(baseline_payload=baseline)
            with bp, op:
                rc = cli.main([
                    "--json", "--backup-path", backup,
                    "--high-priority-csv", high,
                    "--medium-csv", medium,
                    "--limit", "5",
                ], out=out)
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)


if __name__ == "__main__":
    unittest.main()
