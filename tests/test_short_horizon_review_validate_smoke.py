"""Tests for ``scripts/short_horizon_review_validate_smoke.py``.

Pin the contract:

* Operates on a temp DB copy only — live DB read-only, never mutated.
  The temp DB seam is patchable; tests substitute synthetic payloads
  so no real DB / provider / yfinance / FastAPI is touched.
* Reads accepted + excluded rows from a manually reviewed
  short-horizon worksheet via ``--worksheet``.  Worksheet schema only
  requires ``event_id``; the canonical gate column
  ``include_in_short_horizon_validation`` is consulted when present
  (``yes`` / ``no`` / blank, case- and whitespace-insensitive);
  ``exclude_reason`` and ``headline`` are read when present.
* Accepted = ``include_in_short_horizon_validation`` is ``yes``.
* Excluded = ``include_in_short_horizon_validation`` is ``no``; the
  row's ``exclude_reason`` is recorded verbatim.
* Pending = gate is blank or carries an unrecognised value; surfaced
  via warnings, never counted in ``accepted_count`` or
  ``excluded_candidates``.
* Runs validation against the 1d/5d horizons only — 20d records leaked
  by an upstream seam are dropped at the smoke layer.
* Uses existing price_cache only — no provider/yfinance/LLM/FastAPI.
* Output is "reviewed short-horizon evidence" — never "validated
  archive" or "alpha".  Conservative wording is enforced for the
  ``errors`` and ``warnings`` text streams only; record payloads are
  the upstream pipeline's responsibility.
* Output file is only written when ``--output`` (``output_path``) is
  passed; default invocation has no filesystem side effect.
* CLI ``main`` always returns 0 — failure is surfaced via the
  envelope's ``ok`` field, not the exit code, so a missing worksheet
  doesn't break a verification pipeline that calls the script with
  ``--json``.
* Output dict has EXACTLY these 12 keys::

    ok, worksheet_path, accepted_count, events_evaluated,
    records_count, significant_count, by_horizon, by_mechanism_family,
    examples, excluded_candidates, errors, warnings
"""
from __future__ import annotations

import csv as csv_module
import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_validate_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "worksheet_path",
    "accepted_count",
    "events_evaluated",
    "records_count",
    "significant_count",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "excluded_candidates",
    "errors",
    "warnings",
)


_BANNED_WORDS = (
    "proof",
    "alpha generated",
    "automatically",
    "validated archive",
    "guaranteed",
)


# Canonical short-horizon review worksheet columns, in the order
# emitted by ``scripts.short_horizon_review_worksheet``.  The gate
# column is ``include_in_short_horizon_validation``.
_WORKSHEET_COLUMNS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# ---------------------------------------------------------------------------
# Worksheet + payload builders
# ---------------------------------------------------------------------------


def _write_worksheet(
    rows: list[dict], *,
    suffix: str = "ws",
    columns: tuple[str, ...] = _WORKSHEET_COLUMNS,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in columns])
    return path


def _worksheet_row(
    *, event_id: int,
    headline: str = "h",
    event_date: str = "2026-04-05",
    current_primary_ticker: str = "AAPL",
    current_mechanism_family: str = "none",
    repair_type: str = "mechanism_family_only",
    repair_priority: str = "high",
    operator_decision_needed: str = "supply_mechanism_family",
    reason_for_review: str = "",
    proposed_primary_ticker: str = "",
    proposed_benchmark_ticker: str = "",
    proposed_mechanism_family: str = "",
    predicted_direction: str = "",
    include_in_short_horizon_validation: str = "",
    exclude_reason: str = "",
    operator_notes: str = "",
) -> dict:
    return {
        "event_id":                            event_id,
        "headline":                            headline,
        "event_date":                          event_date,
        "current_primary_ticker":              current_primary_ticker,
        "current_mechanism_family":            current_mechanism_family,
        "repair_type":                         repair_type,
        "repair_priority":                     repair_priority,
        "operator_decision_needed":            operator_decision_needed,
        "reason_for_review":                   reason_for_review,
        "proposed_primary_ticker":             proposed_primary_ticker,
        "proposed_benchmark_ticker":           proposed_benchmark_ticker,
        "proposed_mechanism_family":           proposed_mechanism_family,
        "predicted_direction":                 predicted_direction,
        "include_in_short_horizon_validation": include_in_short_horizon_validation,
        "exclude_reason":                      exclude_reason,
        "operator_notes":                      operator_notes,
    }


def _validation_payload(records: list[dict]) -> dict:
    return {
        "ok":      True,
        "records": list(records),
        "errors":  [],
    }


def _validation_record(
    *, event_id: int, horizon: int,
    sar: float = 1.0,
    ticker: str = "AAPL",
    abnormal_return: float = 0.02,
    ci_low: float = -0.01,
    ci_high: float = 0.05,
    p_value: float = 0.1,
    fdr_q: float = 0.2,
    interpretation: str = "not_significant",
    headline: str = "h",
    mechanism_family: str = "supply_shock",
    significant: bool = False,
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "ticker":                    ticker,
        "horizon":                   horizon,
        "abnormal_return":           abnormal_return,
        "sar":                       sar,
        "ci_low":                    ci_low,
        "ci_high":                   ci_high,
        "p_value":                   p_value,
        "fdr_q":                     fdr_q,
        "interpretation":            interpretation,
        "mechanism_family":          mechanism_family,
        "statistically_significant": significant,
    }


def _patched_seam(records: list[dict]):
    return patch.object(
        cli, "_run_short_horizon_validation_on_temp_db",
        return_value=_validation_payload(records),
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_has_exactly_twelve_keys(self) -> None:
        with _patched_seam([]):
            report = cli.run_short_horizon_review_validate(
                worksheet_path=None,
            )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")

    def test_missing_worksheet_fails_closed(self) -> None:
        with _patched_seam([]):
            report = cli.run_short_horizon_review_validate(
                worksheet_path=None,
            )
        self.assertFalse(report["ok"])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["events_evaluated"], 0)
        self.assertEqual(report["records_count"], 0)
        self.assertEqual(report["excluded_candidates"], [])
        self.assertTrue(any(
            "--worksheet" in e or "worksheet" in e.lower()
            for e in report["errors"]
        ))

    def test_nonexistent_worksheet_fails_closed(self) -> None:
        with _patched_seam([]):
            report = cli.run_short_horizon_review_validate(
                worksheet_path="/tmp/definitely-does-not-exist.csv",
            )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "not found" in e.lower() or "does not exist" in e.lower()
            for e in report["errors"]
        ))

    def test_by_horizon_keys_pinned_to_1_and_5(self) -> None:
        path = _write_worksheet([])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(set(report["by_horizon"].keys()), {"1", "5"})
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Worksheet parsing + classification
# ---------------------------------------------------------------------------


class TestWorksheetParsing(unittest.TestCase):
    def test_yes_gate_accepts_row(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="JPM",
                proposed_benchmark_ticker="SPY",
                proposed_mechanism_family="supply_shock",
                predicted_direction="up",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["excluded_candidates"], [])
        finally:
            os.unlink(path)

    def test_yes_gate_case_and_whitespace_insensitive(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="  YES  ",
            ),
        ])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["accepted_count"], 1)
        finally:
            os.unlink(path)

    def test_no_gate_with_exclude_reason_captures_row(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=80,
                include_in_short_horizon_validation="no",
                exclude_reason="off-topic",
            ),
        ])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(len(report["excluded_candidates"]), 1)
            entry = report["excluded_candidates"][0]
            self.assertEqual(entry["event_id"], 80)
            self.assertEqual(entry["reason"], "off-topic")
        finally:
            os.unlink(path)

    def test_proposed_fields_alone_no_longer_accept_row(self) -> None:
        # Pre-alignment behaviour: a row with proposed_primary_ticker
        # and no gate set was inferred as accepted.  The canonical
        # gate column now requires an explicit ``yes`` — proposed-only
        # rows are pending.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                proposed_primary_ticker="JPM",
                proposed_mechanism_family="supply_shock",
                # Gate left blank.
            ),
        ])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(report["excluded_candidates"], [])
            self.assertTrue(any(
                "pending" in w.lower() for w in report["warnings"]
            ), f"warnings: {report['warnings']}")
        finally:
            os.unlink(path)

    def test_pending_row_with_blank_gate_surfaces_warning(self) -> None:
        # Row with blank gate → pending; warning surfaced, not counted
        # in accepted or excluded.
        path = _write_worksheet([
            _worksheet_row(event_id=90),
        ])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(report["excluded_candidates"], [])
            self.assertTrue(any(
                "pending" in w.lower() for w in report["warnings"]
            ), f"warnings: {report['warnings']}")
        finally:
            os.unlink(path)

    def test_worksheet_path_echoed_in_output(self) -> None:
        path = _write_worksheet([])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["worksheet_path"], path)
        finally:
            os.unlink(path)

    def test_worksheet_with_only_event_id_column_still_parses(self) -> None:
        # The schema only requires event_id; missing optional columns
        # are treated as blank, so the row is "pending" (warning).
        path = _write_worksheet(
            [{"event_id": 70}],
            columns=("event_id",),
        )
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            # No errors from the minimal-schema CSV.
            self.assertEqual(report["errors"], [])
        finally:
            os.unlink(path)

    def test_worksheet_missing_event_id_column_fails_closed(self) -> None:
        # Without event_id, no row can be classified.
        path = _write_worksheet(
            [{"headline": "h"}],
            columns=("headline",),
        )
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "event_id" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Records filtering
# ---------------------------------------------------------------------------


class TestRecordsFiltering(unittest.TestCase):
    def test_records_filtered_to_accepted_event_ids(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="JPM",
            ),
            _worksheet_row(
                event_id=71,
                include_in_short_horizon_validation="no",
                exclude_reason="off-topic",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1),
                _validation_record(event_id=70, horizon=5),
                _validation_record(event_id=71, horizon=1),   # excluded
                _validation_record(event_id=999, horizon=1),  # not in worksheet
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["records_count"], 2)
            self.assertEqual(report["events_evaluated"], 1)
        finally:
            os.unlink(path)

    def test_significant_count_counts_significant_records(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="JPM",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1, significant=True),
                _validation_record(event_id=70, horizon=5, significant=False),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["significant_count"], 1)
        finally:
            os.unlink(path)

    def test_examples_capped_at_limit(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=i,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="X",
            )
            for i in range(1, 11)
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=i, horizon=1)
                for i in range(1, 11)
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path, limit=3,
                )
            self.assertEqual(len(report["examples"]), 3)
            # Aggregates reflect EVERY accepted record, not just the
            # capped examples.
            self.assertEqual(report["records_count"], 10)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


class TestAggregates(unittest.TestCase):
    def test_by_horizon_aggregates_counts(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="JPM",
            ),
            _worksheet_row(
                event_id=80,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="MSFT",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1, significant=True),
                _validation_record(event_id=70, horizon=5),
                _validation_record(event_id=80, horizon=1),
                _validation_record(event_id=80, horizon=5, significant=True),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["by_horizon"]["1"]["records_count"], 2)
            self.assertEqual(report["by_horizon"]["1"]["significant_count"], 1)
            self.assertEqual(report["by_horizon"]["5"]["records_count"], 2)
            self.assertEqual(report["by_horizon"]["5"]["significant_count"], 1)
        finally:
            os.unlink(path)

    def test_by_mechanism_family_aggregates(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="supply_shock",
            ),
            _worksheet_row(
                event_id=80,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="commodity_squeeze",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1,
                                   mechanism_family="supply_shock"),
                _validation_record(event_id=70, horizon=5,
                                   mechanism_family="supply_shock"),
                _validation_record(event_id=80, horizon=1,
                                   mechanism_family="commodity_squeeze",
                                   significant=True),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            fam = report["by_mechanism_family"]
            self.assertIn("supply_shock", fam)
            self.assertEqual(fam["supply_shock"]["events_evaluated"], 1)
            self.assertEqual(fam["supply_shock"]["records_count"], 2)
            self.assertEqual(fam["supply_shock"]["significant_count"], 0)
            self.assertIn("commodity_squeeze", fam)
            self.assertEqual(fam["commodity_squeeze"]["significant_count"], 1)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Worksheet metadata carries into validation output
# ---------------------------------------------------------------------------


class TestWorksheetMetadataEnrichment(unittest.TestCase):
    def test_example_mechanism_family_comes_from_worksheet(self) -> None:
        # The operator's proposed_mechanism_family is the post-review
        # source of truth — the example must carry it even when the
        # upstream record's mechanism_family is blank.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="XOM",
                proposed_benchmark_ticker="SPY",
                proposed_mechanism_family="supply_shock",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(
                    event_id=70, horizon=1,
                    mechanism_family="",
                    ticker="",
                ),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            example = report["examples"][0]
            self.assertEqual(example["mechanism_family"], "supply_shock")
        finally:
            os.unlink(path)

    def test_worksheet_overrides_upstream_mechanism_family(self) -> None:
        # The worksheet is post-review; its proposed_mechanism_family
        # overrides whatever value the upstream pipeline attached.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="chokepoint_relief",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(
                    event_id=70, horizon=1,
                    mechanism_family="supply_shock",
                ),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            example = report["examples"][0]
            self.assertEqual(example["mechanism_family"], "chokepoint_relief")
            self.assertIn("chokepoint_relief", report["by_mechanism_family"])
            self.assertNotIn("supply_shock", report["by_mechanism_family"])
        finally:
            os.unlink(path)

    def test_worksheet_primary_and_benchmark_override_example(self) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="XOM",
                proposed_benchmark_ticker="XLE",
                proposed_mechanism_family="supply_shock",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1, ticker="OTHER"),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            example = report["examples"][0]
            self.assertEqual(example["primary_ticker"], "XOM")
            self.assertEqual(example["benchmark"], "XLE")
        finally:
            os.unlink(path)

    def test_multiple_accepted_rows_produce_nonempty_by_mechanism_family(
        self,
    ) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="supply_shock",
            ),
            _worksheet_row(
                event_id=80,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="chokepoint_relief",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1, mechanism_family=""),
                _validation_record(event_id=70, horizon=5, mechanism_family=""),
                _validation_record(event_id=80, horizon=1, mechanism_family=""),
                _validation_record(event_id=80, horizon=5, mechanism_family=""),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            fam = report["by_mechanism_family"]
            self.assertNotEqual(fam, {})
            self.assertEqual(fam["supply_shock"]["events_evaluated"], 1)
            self.assertEqual(fam["supply_shock"]["records_count"], 2)
            self.assertEqual(fam["chokepoint_relief"]["events_evaluated"], 1)
            self.assertEqual(fam["chokepoint_relief"]["records_count"], 2)
        finally:
            os.unlink(path)

    def test_non_accepted_event_does_not_enter_by_mechanism_family(
        self,
    ) -> None:
        # A record whose event_id is excluded ("no") or absent from the
        # worksheet must not enter the by_mechanism_family aggregation
        # even when it carries an upstream mechanism_family value.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="supply_shock",
            ),
            _worksheet_row(
                event_id=80,
                include_in_short_horizon_validation="no",
                exclude_reason="off-topic",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(
                    event_id=70, horizon=1,
                    mechanism_family="supply_shock",
                ),
                _validation_record(
                    event_id=80, horizon=1,
                    mechanism_family="chokepoint_relief",  # must not aggregate
                ),
                _validation_record(
                    event_id=999, horizon=1,
                    mechanism_family="commodity_squeeze",  # must not aggregate
                ),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            fam = report["by_mechanism_family"]
            self.assertEqual(set(fam.keys()), {"supply_shock"})
        finally:
            os.unlink(path)

    def test_pending_row_does_not_enter_by_mechanism_family(self) -> None:
        # A pending row (blank gate) is not accepted; even if upstream
        # surfaces records for its event_id, those records do not
        # aggregate.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                proposed_mechanism_family="supply_shock",
                # Gate left blank → pending.
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(
                    event_id=70, horizon=1,
                    mechanism_family="supply_shock",
                ),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["by_mechanism_family"], {})
        finally:
            os.unlink(path)

    def test_missing_proposed_mechanism_family_surfaces_warning(self) -> None:
        # An accepted row with blank proposed_mechanism_family is
        # surfaced via a clear warning and is dropped from the
        # by_mechanism_family aggregation — never silently bucketed
        # under None.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="XOM",
                # proposed_mechanism_family left blank
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(
                    event_id=70, horizon=1,
                    mechanism_family="supply_shock",
                ),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            # Record still counts in the existing horizon-filtered
            # aggregation.
            self.assertEqual(report["records_count"], 1)
            # But it does NOT enter the mechanism-family aggregation.
            self.assertEqual(report["by_mechanism_family"], {})
            # And the warning names the affected event_id explicitly.
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("proposed_mechanism_family", joined)
            self.assertIn("70", joined)
        finally:
            os.unlink(path)

    def test_worksheet_headline_fills_in_when_record_headline_blank(
        self,
    ) -> None:
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_mechanism_family="supply_shock",
                headline="operator-supplied headline",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1, headline=""),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            example = report["examples"][0]
            self.assertEqual(
                example["headline"], "operator-supplied headline"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Horizon restriction (1d/5d only)
# ---------------------------------------------------------------------------


class TestHorizonRestriction(unittest.TestCase):
    def test_only_1d_and_5d_records_counted(self) -> None:
        # The smoke is pinned to 1d/5d.  If a leaked 20d record arrives
        # from the seam, the smoke drops it at its layer.
        path = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="JPM",
            ),
        ])
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1),
                _validation_record(event_id=70, horizon=5),
                _validation_record(event_id=70, horizon=20),
            ]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            self.assertEqual(report["records_count"], 2)
            self.assertEqual(set(report["by_horizon"].keys()), {"1", "5"})
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Output file persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_output_passed(self) -> None:
        worksheet = _write_worksheet([
            _worksheet_row(
                event_id=70,
                include_in_short_horizon_validation="yes",
                proposed_primary_ticker="JPM",
            ),
        ])
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"out_{uuid.uuid4().hex}.json",
        )
        try:
            with _patched_seam([
                _validation_record(event_id=70, horizon=1),
            ]):
                cli.run_short_horizon_review_validate(
                    worksheet_path=worksheet,
                    output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(set(data.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(data["accepted_count"], 1)
        finally:
            os.unlink(worksheet)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_output_file_when_output_not_passed(self) -> None:
        # Assert default invocation does not write to a candidate path.
        worksheet = _write_worksheet([])
        sentinel = os.path.join(
            tempfile.gettempdir(),
            f"sentinel_{uuid.uuid4().hex}.json",
        )
        self.assertFalse(os.path.exists(sentinel))
        try:
            with _patched_seam([]):
                cli.run_short_horizon_review_validate(
                    worksheet_path=worksheet,
                )
            # No output_path passed → no candidate file created.
            self.assertFalse(os.path.exists(sentinel))
        finally:
            os.unlink(worksheet)

    def test_output_file_written_on_failure_envelope_too(self) -> None:
        # When --output is passed, the file MUST land on disk even
        # when the envelope's ``ok`` is False — a verification
        # pipeline must be able to depend on the artifact existing.
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"fail_{uuid.uuid4().hex}.json",
        )
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path="/tmp/definitely-does-not-exist.csv",
                    output_path=out_path,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(
                os.path.exists(out_path),
                "output file must be written even on failure envelope",
            )
            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(set(data.keys()), set(_REQUIRED_KEYS))
            self.assertFalse(data["ok"])
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_errors_and_warnings(self) -> None:
        path = _write_worksheet([
            _worksheet_row(event_id=90),  # pending → warning
            _worksheet_row(
                event_id=80,
                include_in_short_horizon_validation="no",
                exclude_reason="x",
            ),
        ])
        try:
            with _patched_seam([]):
                report = cli.run_short_horizon_review_validate(
                    worksheet_path=path,
                )
            text = " ".join([
                " ".join(str(e) for e in report.get("errors", [])),
                " ".join(str(w) for w in report.get("warnings", [])),
            ]).lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(
                    w, text,
                    f"banned word {w!r} in errors+warnings: {text!r}",
                )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Seam
# ---------------------------------------------------------------------------


class TestSeam(unittest.TestCase):
    def test_validation_seam_callable(self) -> None:
        self.assertTrue(callable(
            getattr(cli, "_run_short_horizon_validation_on_temp_db"),
        ))


# ---------------------------------------------------------------------------
# Import isolation — no provider / FastAPI / api.* on the un-patched
# default path.
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api")

    def test_smoke_does_not_import_provider_or_fastapi(self) -> None:
        before = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        with _patched_seam([]):
            cli.run_short_horizon_review_validate(worksheet_path=None)
        after = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    with _patched_seam([]):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue()


class TestCLI(unittest.TestCase):
    def test_json_emits_twelve_keys(self) -> None:
        ws = _write_worksheet([])
        try:
            rc, output = _run_cli(["--worksheet", ws, "--json"])
            self.assertEqual(rc, 0)
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(ws)

    def test_text_default_runs(self) -> None:
        ws = _write_worksheet([])
        try:
            rc, output = _run_cli(["--worksheet", ws])
            self.assertEqual(rc, 0)
            self.assertIn("ok", output.lower())
        finally:
            os.unlink(ws)

    def test_missing_worksheet_arg_still_returns_zero(self) -> None:
        # --worksheet is optional at argparse level — the function
        # surfaces the missing-input failure via the envelope so a
        # verification pipeline always gets a valid JSON document.
        rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertFalse(parsed["ok"])
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))

    def test_main_returns_zero_when_envelope_ok_is_false(self) -> None:
        rc, output = _run_cli([
            "--worksheet", "/tmp/nonexistent-worksheet.csv",
            "--json",
        ])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertFalse(parsed["ok"])


if __name__ == "__main__":
    unittest.main()
