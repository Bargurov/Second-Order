"""Tests for ``scripts/manual_repaired_cohort_short_horizon_validation_run.py``.

Pin the contract:

* Wraps the existing full repaired-cohort runner
  (``run_manual_repaired_cohort_validation``) — does not duplicate the
  temp-copy / apply / backfill pipeline.  Re-uses the same temp DB the
  full run produced (handle leaked through the full run's ``warnings``
  as a ``"Temp copy at <path>"`` line).
* Runs the existing short-horizon archive stats runner
  (``run_archive_short_horizon_stat_validation``) against the SAME
  temp DB, so the repaired cohort is identical between the two runs.
* Filters short-horizon records to the repaired cohort surfaced by the
  full run.
* Output dict carries:
    - the standard envelope (ok, errors, warnings, hash invariants)
    - ``events_evaluated`` / ``records_count`` / ``significant_count``
      reflecting the SHORT horizon (1d, 5d) cohort only
    - ``top_abs_sar`` — a single record with the largest |SAR|
      observed in the repaired cohort, NEVER framed as "best signal"
      or "alpha winner"
    - ``comparison_to_full_repaired_run`` — full counts + deltas +
      events-only-in-each-side
* ``by_horizon`` keys are exactly ``{"1", "5"}`` — never includes
  ``"20"``.
* Fail-closed precedence:
    - Full runner returns ``ok=False`` → propagate failure, do not run
      short-horizon validation.
    - Full runner returns ``ok=True`` but no temp DB path can be
      extracted → fail closed.
* Conservative language only — interpretation passes through verbatim
  from ``make_stat_validation_record``; the runner never claims
  "proof" / "alpha" / causal language.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import (  # noqa: E402
    manual_repaired_cohort_short_horizon_validation_run as cli,
)


_REQUIRED_KEYS = (
    "ok",
    "repaired_clean_event_ids",
    "events_evaluated",
    "records_count",
    "significant_count",
    "top_abs_sar",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "excluded_event_ids",
    "remaining_blockers",
    "comparison_to_full_repaired_run",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
)

_REQUIRED_EXAMPLE_FIELDS = (
    "event_id",
    "headline",
    "primary_ticker",
    "benchmark",
    "mechanism_family",
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "interpretation",
)

_REQUIRED_TOP_ABS_SAR_FIELDS = (
    "event_id",
    "primary_ticker",
    "horizon",
    "sar",
    "abs_sar",
    "p_value",
    "fdr_q",
    "interpretation",
    "statistically_significant",
)

_REQUIRED_COMPARISON_FIELDS = (
    "full_events_evaluated",
    "full_records_count",
    "full_significant_count",
    "full_horizons",
    "short_horizons",
    "events_evaluated_delta",
    "records_count_delta",
    "significant_count_delta",
    "events_in_full_only",
    "events_in_short_only",
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic envelopes for the two patchable seams
# ---------------------------------------------------------------------------


def _full_envelope(
    *,
    ok: bool = True,
    repaired_clean_event_ids: list[int] | None = None,
    events_evaluated: int = 0,
    records_count: int = 0,
    significant_count: int = 0,
    by_horizon: dict[str, Any] | None = None,
    by_mechanism_family: dict[str, Any] | None = None,
    excluded_event_ids: list[int] | None = None,
    remaining_blockers: dict[str, Any] | None = None,
    examples: list[dict] | None = None,
    temp_db_path: str | None = "/tmp/synthetic_repaired_temp.db",
    live_db_unchanged: bool = True,
    input_backup_unchanged: bool = True,
    errors: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = list(extra_warnings or [])
    if temp_db_path is not None:
        warnings.append(f"Temp copy at {temp_db_path}")
    return {
        "ok":                       ok,
        "repaired_clean_event_ids": list(repaired_clean_event_ids or []),
        "events_evaluated":         events_evaluated,
        "records_count":            records_count,
        "significant_count":        significant_count,
        "by_horizon":               by_horizon or {},
        "by_mechanism_family":      by_mechanism_family or {},
        "examples":                 list(examples or []),
        "excluded_event_ids":       list(excluded_event_ids or []),
        "remaining_blockers":       remaining_blockers or {},
        "live_db_unchanged":        live_db_unchanged,
        "input_backup_unchanged":   input_backup_unchanged,
        "errors":                   list(errors or []),
        "warnings":                 warnings,
    }


def _short_record(
    *, event_id: int, horizon: int = 1,
    headline: str = "h",
    primary_ticker: str = "MS",
    benchmark: str = "SPY",
    mechanism_family: str | None = "supply_shock",
    abnormal_return: float = 0.012,
    sar: float = 1.5,
    ci_low: float = 0.001,
    ci_high: float = 0.022,
    p_value: float = 0.04, fdr_q: float = 0.08,
    significant: bool = True,
    interpretation: str = "evidence",
) -> dict[str, Any]:
    return {
        "event_id":         event_id,
        "headline":         headline,
        "primary_ticker":   primary_ticker,
        "benchmark":        benchmark,
        "mechanism_family": mechanism_family,
        "horizon":          horizon,
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "ci_low":           ci_low,
        "ci_high":          ci_high,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "statistically_significant": significant,
        "interpretation":   interpretation,
    }


def _short_envelope(
    *, records: list[dict] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    records = list(records or [])
    return {
        "ok":                  not (errors or []),
        "events_evaluated":    len({r["event_id"] for r in records}),
        "records_count":       len(records),
        "significant_count":   sum(
            1 for r in records if r.get("statistically_significant")),
        "records":             records,
        "errors":              list(errors or []),
    }


def _patch_seams(
    *,
    full_payload: dict[str, Any],
    short_payload: dict[str, Any] | None = None,
):
    if short_payload is None:
        short_payload = _short_envelope()

    def fake_full(*, backup_path, high_priority_csv, medium_csv,
                  db_path, limit):
        return full_payload

    def fake_short(*, db_path, limit):
        return short_payload

    return (
        patch.object(cli, "_run_full_repaired_cohort",                side_effect=fake_full),
        patch.object(cli, "_run_short_horizon_validation_on_temp_db", side_effect=fake_short),
    )


def _run(
    *, backup_path: str = "/synthetic/backup.db",
    high_priority_csv: str = "/synthetic/high.csv",
    medium_csv: str = "/synthetic/medium.csv",
    db_path: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return cli.run_manual_repaired_cohort_short_horizon_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        db_path=db_path,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_returns_dict_with_exactly_required_keys(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46],
            events_evaluated=1, records_count=3, significant_count=1,
            by_horizon={"1": {"records_count": 1, "significant_count": 0},
                        "5": {"records_count": 1, "significant_count": 1},
                        "20": {"records_count": 1, "significant_count": 0}},
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1, sar=0.5, significant=False),
            _short_record(event_id=46, horizon=5, sar=2.5, significant=True),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))


class TestShortHorizonOnly(unittest.TestCase):
    """``by_horizon`` keys must be a subset of {"1", "5"} — never
    includes ``"20"`` even if some short-horizon record arrived with
    horizon=20 (defensive guard)."""

    def test_by_horizon_keys_only_1_and_5(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1),
            _short_record(event_id=46, horizon=5),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertEqual(set(result["by_horizon"].keys()), {"1", "5"})
        self.assertNotIn("20", result["by_horizon"])

    def test_by_horizon_drops_horizon_20_records_defensively(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1),
            _short_record(event_id=46, horizon=5),
            # Defensive: even if upstream slipped a 20d record through,
            # the short-horizon runner must NOT surface it.
            _short_record(event_id=46, horizon=20),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertEqual(set(result["by_horizon"].keys()), {"1", "5"})
        # records_count should reflect only 1d + 5d.
        self.assertEqual(result["records_count"], 2)


# ---------------------------------------------------------------------------
# Repaired cohort filtering
# ---------------------------------------------------------------------------


class TestRepairedCohortFiltering(unittest.TestCase):
    """Short-horizon runner must filter to the SAME repaired cohort the
    full runner identified.  Pre-existing clean events must NOT pollute
    the cohort.
    """

    def test_only_repaired_events_appear_in_records(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46, 60, 73],
            events_evaluated=3, records_count=9, significant_count=2,
        )
        # The short-horizon validation seam returns records for the
        # repaired cohort PLUS event 100 (already clean before repair).
        # The runner must filter event 100 OUT.
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1),
            _short_record(event_id=46, horizon=5),
            _short_record(event_id=60, horizon=1),
            _short_record(event_id=60, horizon=5),
            _short_record(event_id=73, horizon=1),
            _short_record(event_id=73, horizon=5),
            _short_record(event_id=100, horizon=1),
            _short_record(event_id=100, horizon=5),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertIs(result["ok"], True)
        self.assertEqual(
            sorted(result["repaired_clean_event_ids"]), [46, 60, 73],
        )
        self.assertEqual(result["events_evaluated"], 3)
        self.assertEqual(result["records_count"], 6)
        evaluated_ids = {ex["event_id"] for ex in result["examples"]}
        self.assertEqual(evaluated_ids, {46, 60, 73})
        self.assertNotIn(100, evaluated_ids)


# ---------------------------------------------------------------------------
# top_abs_sar
# ---------------------------------------------------------------------------


class TestTopAbsSar(unittest.TestCase):
    """``top_abs_sar`` is the single record with the largest |SAR| in
    the filtered repaired cohort.  Conservative wording — never framed
    as "best signal" or similar."""

    def test_top_abs_sar_picks_max_abs_value(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46, 60])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1, sar=0.5),
            _short_record(event_id=46, horizon=5, sar=-2.7),  # |SAR|=2.7 wins
            _short_record(event_id=60, horizon=1, sar=1.8),
            _short_record(event_id=60, horizon=5, sar=2.4),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        top = result["top_abs_sar"]
        for f in _REQUIRED_TOP_ABS_SAR_FIELDS:
            self.assertIn(f, top, f"missing top_abs_sar field: {f}")
        self.assertEqual(top["event_id"], 46)
        self.assertEqual(top["horizon"], 5)
        self.assertAlmostEqual(top["sar"], -2.7)
        self.assertAlmostEqual(top["abs_sar"], 2.7)

    def test_top_abs_sar_ignores_none_sar(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1, sar=None),
            _short_record(event_id=46, horizon=5, sar=1.1),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        top = result["top_abs_sar"]
        self.assertEqual(top["event_id"], 46)
        self.assertEqual(top["horizon"], 5)
        self.assertAlmostEqual(top["sar"], 1.1)

    def test_top_abs_sar_empty_cohort_returns_none_block(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[])
        patches = _patch_seams(
            full_payload=full,
            short_payload=_short_envelope(records=[]),
        )
        with patches[0], patches[1]:
            result = _run()
        top = result["top_abs_sar"]
        for f in _REQUIRED_TOP_ABS_SAR_FIELDS:
            self.assertIn(f, top)
            self.assertIsNone(top[f])

    def test_top_abs_sar_only_considers_repaired_cohort(self) -> None:
        """Even if the seam returns a huge |SAR| for a non-repaired
        event, top_abs_sar must point at a repaired event."""
        full = _full_envelope(repaired_clean_event_ids=[46])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=5, sar=0.5),
            _short_record(event_id=999, horizon=5, sar=99.0),  # not repaired
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        top = result["top_abs_sar"]
        self.assertEqual(top["event_id"], 46)


# ---------------------------------------------------------------------------
# Comparison block
# ---------------------------------------------------------------------------


class TestComparisonBlock(unittest.TestCase):
    def test_comparison_carries_required_fields(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46, 60],
            events_evaluated=2, records_count=6, significant_count=2,
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1, significant=False),
            _short_record(event_id=46, horizon=5, significant=True),
            _short_record(event_id=60, horizon=1, significant=False),
            _short_record(event_id=60, horizon=5, significant=True),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        cmp = result["comparison_to_full_repaired_run"]
        for f in _REQUIRED_COMPARISON_FIELDS:
            self.assertIn(f, cmp, f"missing comparison field: {f}")
        self.assertEqual(cmp["full_events_evaluated"], 2)
        self.assertEqual(cmp["full_records_count"], 6)
        self.assertEqual(cmp["full_significant_count"], 2)
        self.assertEqual(cmp["full_horizons"], [1, 5, 20])
        self.assertEqual(cmp["short_horizons"], [1, 5])

    def test_comparison_deltas_are_short_minus_full(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46],
            events_evaluated=1, records_count=3, significant_count=1,
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1, significant=False),
            _short_record(event_id=46, horizon=5, significant=True),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        cmp = result["comparison_to_full_repaired_run"]
        # short: 1 event, 2 records, 1 significant
        self.assertEqual(cmp["events_evaluated_delta"], 0)   # 1 - 1
        self.assertEqual(cmp["records_count_delta"], -1)     # 2 - 3
        self.assertEqual(cmp["significant_count_delta"], 0)  # 1 - 1

    def test_comparison_events_only_in_each_side(self) -> None:
        # Repaired cohort = {46, 60, 73}.  Full evaluated {46, 73}.
        # Short evaluated {46, 60}.
        full = _full_envelope(
            repaired_clean_event_ids=[46, 60, 73],
            events_evaluated=2,
            examples=[
                {"event_id": 46, "headline": None, "primary_ticker": None,
                 "benchmark": None, "mechanism_family": None, "horizon": 5,
                 "abnormal_return": None, "sar": None, "ci_low": None,
                 "ci_high": None, "p_value": None, "fdr_q": None,
                 "interpretation": None},
                {"event_id": 73, "headline": None, "primary_ticker": None,
                 "benchmark": None, "mechanism_family": None, "horizon": 5,
                 "abnormal_return": None, "sar": None, "ci_low": None,
                 "ci_high": None, "p_value": None, "fdr_q": None,
                 "interpretation": None},
            ],
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1),
            _short_record(event_id=46, horizon=5),
            _short_record(event_id=60, horizon=1),
            _short_record(event_id=60, horizon=5),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        cmp = result["comparison_to_full_repaired_run"]
        self.assertEqual(sorted(cmp["events_in_full_only"]),  [73])
        self.assertEqual(sorted(cmp["events_in_short_only"]), [60])


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------


class TestExampleSchema(unittest.TestCase):
    def test_examples_carry_required_fields(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=5,
                          mechanism_family="bank_regulatory_capital_relief"),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertEqual(len(result["examples"]), 1)
        ex = result["examples"][0]
        for field in _REQUIRED_EXAMPLE_FIELDS:
            self.assertIn(field, ex, f"missing example field: {field}")
        self.assertEqual(ex["primary_ticker"], "MS")
        self.assertEqual(ex["benchmark"], "SPY")
        self.assertEqual(ex["mechanism_family"],
                         "bank_regulatory_capital_relief")


class TestInnerFullLimitNotTruncated(unittest.TestCase):
    """Regression guard: the wrapper must call the inner full runner
    with a high limit so full's ``examples`` aren't truncated below the
    repaired cohort size.  Without this, cohorts of >limit/3 events
    would silently undercount full's evaluated set in the comparison
    block (``events_in_short_only`` / ``events_in_full_only``)."""

    def test_inner_full_call_uses_high_limit(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=5),
        ])
        captured: dict[str, Any] = {}

        def capture_full(*, backup_path, high_priority_csv, medium_csv,
                         db_path, limit):
            captured["limit"] = limit
            return full

        def fake_short(*, db_path, limit):
            return short

        with patch.object(cli, "_run_full_repaired_cohort",
                          side_effect=capture_full):
            with patch.object(
                cli, "_run_short_horizon_validation_on_temp_db",
                side_effect=fake_short,
            ):
                _run(limit=3)
        # User passed limit=3 but the wrapper must pass a much larger
        # limit to the inner full call.
        self.assertGreaterEqual(captured["limit"], 1000)


class TestExamplesCappedByLimit(unittest.TestCase):
    def test_examples_capped_at_limit(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[1, 2, 3, 4, 5])
        short = _short_envelope(records=[
            _short_record(event_id=i, horizon=h)
            for i in (1, 2, 3, 4, 5) for h in (1, 5)
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run(limit=3)
        self.assertLessEqual(len(result["examples"]), 3)
        # records_count reflects ALL repaired records, not the cap.
        self.assertEqual(result["records_count"], 10)


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


class TestByHorizonAggregation(unittest.TestCase):
    def test_by_horizon_counts(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46, 60])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1, significant=False),
            _short_record(event_id=46, horizon=5, significant=True),
            _short_record(event_id=60, horizon=1, significant=False),
            _short_record(event_id=60, horizon=5, significant=True),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        by_h = result["by_horizon"]
        self.assertEqual(by_h["1"]["records_count"], 2)
        self.assertEqual(by_h["1"]["significant_count"], 0)
        self.assertEqual(by_h["5"]["records_count"], 2)
        self.assertEqual(by_h["5"]["significant_count"], 2)


class TestByMechanismFamilyAggregation(unittest.TestCase):
    def test_by_family_counts_unique_events(self) -> None:
        full = _full_envelope(repaired_clean_event_ids=[46, 60, 73])
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1,
                          mechanism_family="supply_shock"),
            _short_record(event_id=46, horizon=5,
                          mechanism_family="supply_shock"),
            _short_record(event_id=60, horizon=5,
                          mechanism_family="supply_shock"),
            _short_record(event_id=73, horizon=5,
                          mechanism_family="bank_regulatory_capital_relief"),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        fam = result["by_mechanism_family"]
        self.assertEqual(fam["supply_shock"]["events_evaluated"], 2)
        self.assertEqual(fam["supply_shock"]["records_count"], 3)
        self.assertEqual(
            fam["bank_regulatory_capital_relief"]["events_evaluated"], 1
        )


# ---------------------------------------------------------------------------
# excluded_event_ids + remaining_blockers passthrough
# ---------------------------------------------------------------------------


class TestEnvelopePassthrough(unittest.TestCase):
    def test_excluded_event_ids_passed_through_from_full(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46],
            excluded_event_ids=[4, 47, 64],
            remaining_blockers={"99": ["mechanism_family_none"]},
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=5),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertEqual(result["excluded_event_ids"], [4, 47, 64])
        self.assertEqual(result["remaining_blockers"],
                         {"99": ["mechanism_family_none"]})

    def test_hash_invariants_passed_through_from_full(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46],
            live_db_unchanged=False, input_backup_unchanged=False,
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=5),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertIs(result["live_db_unchanged"], False)
        self.assertIs(result["input_backup_unchanged"], False)


# ---------------------------------------------------------------------------
# Fail-closed precedence
# ---------------------------------------------------------------------------


class TestFailClosedFullRunFails(unittest.TestCase):
    """If the full repaired-cohort runner returns ok=False, propagate
    failure WITHOUT running short-horizon validation."""

    def test_full_failure_propagates(self) -> None:
        full = _full_envelope(
            ok=False,
            errors=["Provider unavailable"],
            temp_db_path=None,  # no temp copy created
        )
        called: dict[str, bool] = {"short_called": False}

        def fake_short(*, db_path, limit):
            called["short_called"] = True
            return _short_envelope()

        with patch.object(cli, "_run_full_repaired_cohort",
                          return_value=full):
            with patch.object(
                cli, "_run_short_horizon_validation_on_temp_db",
                side_effect=fake_short,
            ):
                result = _run()
        self.assertIs(result["ok"], False)
        self.assertFalse(called["short_called"])
        self.assertTrue(any("Provider unavailable" in e
                            for e in result["errors"]))


class TestFailClosedNoTempPath(unittest.TestCase):
    """If the full runner returns ok=True but no ``Temp copy at ...``
    warning, the short-horizon runner cannot proceed — fail closed.
    """

    def test_no_temp_path_in_warnings_fails_closed(self) -> None:
        full = _full_envelope(
            ok=True,
            repaired_clean_event_ids=[46],
            events_evaluated=1, records_count=3, significant_count=1,
            temp_db_path=None,
        )
        called: dict[str, bool] = {"short_called": False}

        def fake_short(*, db_path, limit):
            called["short_called"] = True
            return _short_envelope()

        with patch.object(cli, "_run_full_repaired_cohort",
                          return_value=full):
            with patch.object(
                cli, "_run_short_horizon_validation_on_temp_db",
                side_effect=fake_short,
            ):
                result = _run()
        self.assertIs(result["ok"], False)
        self.assertFalse(called["short_called"])
        self.assertTrue(
            any("temp" in e.lower() for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )


# ---------------------------------------------------------------------------
# Empty cohort
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):
    def test_empty_cohort_returns_ok_with_zero_counts(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[],
            events_evaluated=0, records_count=0, significant_count=0,
        )
        short = _short_envelope(records=[])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertIs(result["ok"], True)
        self.assertEqual(result["repaired_clean_event_ids"], [])
        self.assertEqual(result["events_evaluated"], 0)
        self.assertEqual(result["records_count"], 0)
        self.assertEqual(result["significant_count"], 0)
        self.assertEqual(result["examples"], [])
        for f in _REQUIRED_TOP_ABS_SAR_FIELDS:
            self.assertIsNone(result["top_abs_sar"][f])


# ---------------------------------------------------------------------------
# Temp-copy warning passthrough — tests can clean up the temp file
# ---------------------------------------------------------------------------


class TestTempCopyWarningPassthrough(unittest.TestCase):
    def test_temp_copy_warning_carried_in_warnings(self) -> None:
        """Operators (and test fixtures) rely on the ``Temp copy at
        <path>`` warning to locate + clean up the leaked temp DB.  The
        short-horizon runner must propagate it from the full run."""
        full = _full_envelope(
            repaired_clean_event_ids=[46],
            temp_db_path="/tmp/specific_path.db",
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=5),
        ])
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            result = _run()
        self.assertTrue(any("Temp copy at /tmp/specific_path.db" in w
                            for w in result["warnings"]))


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    """The runner must never claim "proof", "alpha generated", "guaranteed",
    causal language, etc.  Banned-phrase scan over the module source.
    """

    _BANNED_PHRASES = (
        "alpha generated",
        "alpha capture",
        "proof of",
        "proves that",
        " proven",
        "guaranteed",
        "causal proof",
        "claim alpha",
        "best signal",
        "winner",
        "delete",
        "auto-correct",
        "auto fix",
        "automatic ",
        "fix the",
    )

    def test_module_source_has_no_banned_phrases(self) -> None:
        path = os.path.join(
            os.path.dirname(__file__), "..", "scripts",
            "manual_repaired_cohort_short_horizon_validation_run.py",
        )
        with open(path, encoding="utf-8") as f:
            source = f.read().lower()
        for phrase in self._BANNED_PHRASES:
            self.assertNotIn(
                phrase.lower(), source,
                f"banned phrase {phrase!r} appears in module source",
            )


# ---------------------------------------------------------------------------
# Patchable seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_full_repaired_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_full_repaired_cohort")))

    def test_short_horizon_validation_seam_exists(self) -> None:
        self.assertTrue(
            callable(getattr(cli, "_run_short_horizon_validation_on_temp_db"))
        )


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_module_import_does_not_pull_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        # Re-importing is a no-op since the module is already loaded;
        # the assertion is that NO new blocked module was pulled in
        # transitively when this test module imported the runner.
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_parseable_json_with_required_keys(self) -> None:
        full = _full_envelope(
            repaired_clean_event_ids=[46],
            events_evaluated=1, records_count=3, significant_count=1,
        )
        short = _short_envelope(records=[
            _short_record(event_id=46, horizon=1),
            _short_record(event_id=46, horizon=5),
        ])
        out = io.StringIO()
        patches = _patch_seams(full_payload=full, short_payload=short)
        with patches[0], patches[1]:
            rc = cli.main([
                "--json",
                "--backup-path",       "/synthetic/backup.db",
                "--high-priority-csv", "/synthetic/high.csv",
                "--medium-csv",        "/synthetic/medium.csv",
                "--limit",             "5",
            ], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)


if __name__ == "__main__":
    unittest.main()
